"""Optional host adapter; importing this package does not register any tools."""
from .adapter import HostProfile, search_read, status
from .contracts import SEARCH_READ_SCHEMA, STATUS_SCHEMA
