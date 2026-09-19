/**
 * Display strings for the assistant's identity.
 *
 * The agent's real name is defined in `backend/core/persona.py` and arrives
 * with the agent list from AgentOS. The frontend cannot import across that
 * service boundary, so `DEFAULT_AGENT_NAME` is a mirror of it: the name shown
 * before the backend has answered, or when it is unreachable. Renaming the
 * agent means editing both. Keeping the mirror in one place is the point --
 * these strings were previously copied across ten call sites in chat and
 * voice, and a copy edit that missed one split the label between components.
 */

/** Fallback shown when no live agent name is available. */
export const DEFAULT_AGENT_NAME = 'Clyde'

/** Label for the voice session, shown in the modal header and control bar. */
export const VOICE_MODE_LABEL = 'Portfolio voice agent'
