'use client'

/**
 * Audio-reactive aura ring for the voice sheet.
 *
 * A WebGL fragment shader traces a ring through layered turbulence many times,
 * accumulating soft-edged light and tone-mapping it (no bloom, which hazes it).
 * The technique is the published one behind LiveKit's Aura; the shader here is
 * our own code (LiveKit's file is Polyform Non-Resale, not Apache).
 *
 * Per-frame work never touches React: the animation loop reads `getLevel()`
 * and writes uniforms. React only changes `state`, which retargets the eased
 * parameters. Decorative only; the sheet's status text carries the state.
 */

import React, { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

export type AuraState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'muted'
  | 'dropped'
  | 'error'

interface Target {
  color: string
  speed: number
  scale: number
  amp: number
  freq: number
  /** Brightness pulses between these two values. */
  bright: [number, number]
  /** Seconds per half pulse. */
  pulse: number
}

const TARGETS: Record<AuraState, Target> = {
  // Start screen: a calm, inviting ember glow.
  idle: {
    color: '#f48c06',
    speed: 12,
    scale: 0.27,
    amp: 1,
    freq: 0.5,
    bright: [1.2, 1.7],
    pulse: 1.6
  },
  connecting: {
    color: '#f48c06',
    speed: 16,
    scale: 0.26,
    amp: 0.5,
    freq: 0.8,
    bright: [0.8, 1.5],
    pulse: 0.9
  },
  listening: {
    color: '#38bdf8',
    speed: 14,
    scale: 0.3,
    amp: 0.8,
    freq: 0.6,
    bright: [1.5, 2],
    pulse: 0.9
  },
  thinking: {
    color: '#a78bfa',
    speed: 18,
    scale: 0.26,
    amp: 0.5,
    freq: 0.8,
    bright: [0.9, 1.8],
    pulse: 1.1
  },
  speaking: {
    color: '#f48c06',
    speed: 32,
    scale: 0.3,
    amp: 0.7,
    freq: 0.9,
    bright: [1.5, 1.5],
    pulse: 1
  },
  muted: {
    color: '#64748b',
    speed: 8,
    scale: 0.22,
    amp: 1.2,
    freq: 0.4,
    bright: [0.7, 0.7],
    pulse: 1
  },
  dropped: {
    color: '#f43f5e',
    speed: 4,
    scale: 0.2,
    amp: 1.2,
    freq: 0.4,
    bright: [0.6, 0.6],
    pulse: 1
  },
  error: {
    color: '#f43f5e',
    speed: 4,
    scale: 0.2,
    amp: 1.2,
    freq: 0.4,
    bright: [0.6, 0.6],
    pulse: 1
  }
}

/** States whose size follows the audio level. */
const REACTIVE: AuraState[] = ['listening', 'speaking']
const MAX_DPR = 2

const VERT = 'attribute vec2 a;void main(){gl_Position=vec4(a,0.0,1.0);}'
const FRAG = `
precision highp float;
uniform vec2 uRes; uniform float uTime; uniform vec3 uColor;
uniform float uSpeed, uAmp, uFreq, uScale, uBright;
vec3 hue(vec3 c, float h){
  const vec3 k = vec3(0.57735);
  float ca = cos(h);
  return c*ca + cross(k, c)*sin(h) + k*dot(k, c)*(1.0-ca);
}
vec2 warp(vec2 p, float t, float it){
  mat2 r = mat2(0.6, -0.25, 0.25, 0.9);
  mat2 lr = mat2(0.6, -0.8, 0.8, 0.6);
  float f = mix(2.0, 14.0, uFreq), a = uAmp;
  for (int i = 0; i < 4; i++){
    vec2 w = sin(f*(p*r) + float(i)*t + it);
    p += (a/f) * r[0] * w;
    r *= lr; f *= 1.4;
  }
  return p;
}
void main(){
  vec2 p = gl_FragCoord.xy / uRes - 0.5;
  p.x *= uRes.x / uRes.y;
  // uTime is a phase accumulated on the CPU (speed already applied), so a
  // speed change bends the motion instead of jumping it.
  float t = uTime;
  vec3 core = vec3(0.0);
  vec2 prev = warp(p, t, -1.0/32.0);
  for (float i = 1.0; i <= 32.0; i++){
    float it = i/32.0;
    vec2 q = warp(p, t, it*3.6);
    float d = abs(length(q) - uScale);
    float mv = distance(q, prev); prev = q;
    float blur = (exp2(mv*2.885) - 1.0) * 0.5;
    vec3 c = hue(uColor, -(1.0-it)*0.05);
    // Edge width in real pixels, so a large aura stays sharp.
    core += (1.0 - smoothstep(0.0, 1.5/uRes.y + blur, d)) * c;
  }
  core /= 32.0;
  // No bloom term: a crisp ribbon of light, not a hazy disc.
  vec3 col = core * 2.2 * uBright;
  // Tone-map brightness, not each channel: per-channel mapping squashed
  // red and lifted green, turning ember into yellow.
  float peak = max(col.r, max(col.g, col.b)) * 4.0;
  col *= (peak / (1.0 + peak)) / max(peak / 4.0, 1e-4);
  // Fade to exactly zero well inside the canvas so no edge ever shows,
  // then drop the faintest haze.
  col *= 1.0 - smoothstep(0.34, 0.5, length(p));
  float m = max(col.r, max(col.g, col.b));
  col *= smoothstep(0.02, 0.08, m);
  // Premultiplied: the glow adds light onto whatever is behind the canvas.
  gl_FragColor = vec4(col, max(col.r, max(col.g, col.b)));
}`

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]
}

interface Spring {
  x: number
  v: number
}

function spring(s: Spring, target: number, dt: number, k = 40, damp = 13) {
  s.v += (target - s.x) * k * dt
  s.v *= Math.exp(-damp * dt)
  s.x += s.v * dt
  return s.x
}

interface VoiceAuraProps {
  state: AuraState
  /** Current audio level, 0..1. Read every frame; keep it cheap. */
  getLevel: () => number
  className?: string
}

export function VoiceAura({ state, getLevel, className }: VoiceAuraProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stateRef = useRef(state)
  const levelRef = useRef(getLevel)
  /** Bumped to request one frame when animation is otherwise stopped. */
  const redrawRef = useRef<() => void>(() => {})
  const [supported, setSupported] = useState(true)

  stateRef.current = state
  levelRef.current = getLevel

  useEffect(() => {
    redrawRef.current()
  }, [state])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const gl = canvas.getContext('webgl', {
      premultipliedAlpha: true,
      alpha: true
    })
    if (!gl) {
      setSupported(false)
      return
    }

    const compile = (type: number, src: string) => {
      const sh = gl.createShader(type)!
      gl.shaderSource(sh, src)
      gl.compileShader(sh)
      return sh
    }
    const program = gl.createProgram()!
    gl.attachShader(program, compile(gl.VERTEX_SHADER, VERT))
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAG))
    gl.linkProgram(program)
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error(
        'Voice aura shader failed to link:',
        gl.getProgramInfoLog(program)
      )
      setSupported(false)
      return
    }
    gl.useProgram(program)
    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW
    )
    const loc = gl.getAttribLocation(program, 'a')
    gl.enableVertexAttribArray(loc)
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)

    const u = (name: string) => gl.getUniformLocation(program, name)
    const U = {
      res: u('uRes'),
      time: u('uTime'),
      color: u('uColor'),
      speed: u('uSpeed'),
      amp: u('uAmp'),
      freq: u('uFreq'),
      scale: u('uScale'),
      bright: u('uBright')
    }

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)')
    const first = TARGETS[stateRef.current]
    const sim = {
      t: 0,
      phase: 0,
      env: 0,
      pulsePhase: 0,
      pulseRate: 1 / first.pulse,
      speed: first.speed,
      color: hexToRgb(first.color),
      scale: { x: first.scale, v: 0 },
      amp: { x: first.amp, v: 0 },
      freq: { x: first.freq, v: 0 }
    }

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR)
      const w = Math.round(canvas.clientWidth * dpr)
      const h = Math.round(canvas.clientHeight * dpr)
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w
        canvas.height = h
      }
    }

    const draw = (dt: number) => {
      const st = stateRef.current
      const target = TARGETS[st]
      const level = REACTIVE.includes(st)
        ? Math.min(1, Math.max(0, levelRef.current()))
        : 0
      sim.phase += dt
      sim.speed += (target.speed - sim.speed) * Math.min(1, dt * 1.2)
      // Voice envelope: rise quickly with a syllable, fall slowly, so the
      // ring breathes with speech instead of jittering on every sample.
      const env = level > sim.env ? 0.25 : 0.04
      sim.env += (level - sim.env) * Math.min(1, env * dt * 60)
      // Near-critically damped: swells and settles without shaking.
      const scale = spring(sim.scale, target.scale + sim.env * 0.12, dt, 90, 18)
      // Always drifting; sound is the response: silence keeps a gentle
      // living motion, the voice envelope lifts wave height and pace.
      const amp = spring(sim.amp, target.amp * 0.6 + sim.env * 0.7, dt)
      const freq = spring(sim.freq, target.freq, dt)
      // Phase advances by the eased rate, so a state change never jumps the pulse.
      sim.pulseRate +=
        (1 / target.pulse - sim.pulseRate) * Math.min(1, dt * 1.5)
      sim.pulsePhase += dt * sim.pulseRate
      const pulse = 0.5 + 0.5 * Math.sin(sim.pulsePhase * Math.PI)
      const bright =
        target.bright[0] +
        (target.bright[1] - target.bright[0]) * pulse +
        sim.env * 0.45
      const goal = hexToRgb(target.color)
      const k = Math.min(1, dt * 3)
      sim.color = sim.color.map((c, i) => c + (goal[i] - c) * k) as [
        number,
        number,
        number
      ]

      resize()
      gl.viewport(0, 0, canvas.width, canvas.height)
      gl.clearColor(0, 0, 0, 0)
      gl.clear(gl.COLOR_BUFFER_BIT)
      gl.uniform2f(U.res, canvas.width, canvas.height)
      sim.t += dt * 0.05 * (sim.speed * 0.6 + sim.env * 20)
      gl.uniform1f(U.time, sim.t)
      gl.uniform3fv(U.color, sim.color)
      gl.uniform1f(U.speed, sim.speed)
      gl.uniform1f(U.amp, amp)
      gl.uniform1f(U.freq, freq)
      gl.uniform1f(U.scale, scale * 0.85)
      gl.uniform1f(U.bright, bright / 1.5)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
    }

    /** Still frame: settle the springs and colour on the current state. */
    const still = () => {
      for (let i = 0; i < 60; i++) draw(1 / 30)
    }

    let raf = 0
    let prev = performance.now()
    const loop = (now: number) => {
      const dt = Math.min(0.05, (now - prev) / 1000)
      prev = now
      draw(dt)
      raf = requestAnimationFrame(loop)
    }
    const run = () => {
      cancelAnimationFrame(raf)
      if (reduce.matches) {
        still()
        return
      }
      // Paused in a background tab, but never left blank.
      if (document.hidden) {
        still()
        return
      }
      prev = performance.now()
      raf = requestAnimationFrame(loop)
    }
    redrawRef.current = () => {
      if (reduce.matches || document.hidden) still()
    }

    run()
    document.addEventListener('visibilitychange', run)
    reduce.addEventListener('change', run)
    return () => {
      cancelAnimationFrame(raf)
      document.removeEventListener('visibilitychange', run)
      reduce.removeEventListener('change', run)
      redrawRef.current = () => {}
      gl.deleteBuffer(buffer)
      gl.deleteProgram(program)
    }
  }, [])

  const color = TARGETS[state].color
  return (
    <div className={cn('relative', className)} aria-hidden="true">
      {supported ? (
        <canvas ref={canvasRef} className="size-full" />
      ) : (
        <div
          className="absolute inset-[18%] rounded-full transition-[box-shadow,border-color] duration-500"
          style={{
            border: `2px solid ${color}`,
            boxShadow: `0 0 40px ${color}, inset 0 0 40px ${color}55`
          }}
        />
      )}
    </div>
  )
}

export default VoiceAura
