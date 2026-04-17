"""Primary views — pages in the shell's main content stack.

Distinct from `overlays/`: overlays are modal widgets (ModalCard with
backdrop, focus trap, close affordances). Views here are full-viewport
pages activated from ToolRail navigation; they have no dismiss chrome
and stay alive across switches so state is preserved when the operator
navigates away and back.
"""
