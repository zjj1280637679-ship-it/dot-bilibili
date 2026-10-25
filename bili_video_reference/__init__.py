"""Opt-in video-reference entry; importing does not register or invoke tools."""
from .adapter import read_video
from .contracts import READ_VIDEO_SCHEMA, TOOL_DEFINITION, resolve

__all__ = ['read_video', 'READ_VIDEO_SCHEMA', 'TOOL_DEFINITION', 'resolve']
