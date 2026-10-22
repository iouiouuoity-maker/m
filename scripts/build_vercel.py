"""Make the static output without copying server source or secrets."""
from pathlib import Path
import shutil
root=Path(__file__).resolve().parents[1]
out=root/'public'
if out.exists():shutil.rmtree(out)
shutil.copytree(root/'dist',out)
assert (out/'index.html').is_file()
assert (root/'api/index.py').is_file()
print('Static output prepared; classroom API uses the Vercel Python runtime.')
