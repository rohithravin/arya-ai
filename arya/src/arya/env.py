"""Environment loading shared by every entrypoint.

Importing this module loads `.env` (project values win over the shell), so
any code path that reads settings — including key-free ones like the
`memories` CLI that must not import arya.config — sees the same values.
"""

from dotenv import load_dotenv

load_dotenv(override=True)
