"""TermScope — a local-only Windows app that explains tech & business jargon.

Two input sources feed a term matcher:
  * live audio (system loopback + microphone) transcribed with a local STT engine
  * text you highlight anywhere, explained on a global hotkey

Matched terms you don't already know are surfaced as discrete notifications with a
"Mark learned" action. Everything runs offline; audio never leaves the machine.
"""

__version__ = "0.1.0"
APP_NAME = "TermScope"
