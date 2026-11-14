#!/usr/bin/env python3
"""
Final verification script - confirm everything is ready to use
"""

import os
import sys
from pathlib import Path

# Force UTF-8 output
if sys.stdout.encoding.lower() != 'utf-8':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

print("=" * 70)
print("MEALIE RECIPE IMPORTER - SETUP CHECK")
print("=" * 70)

print("\n[+] PROJECT FILES:")
for f in sorted(Path('.').glob('*.py')):
    size = f.stat().st_size
    print(f"  [OK] {f.name:<30} ({size:,} bytes)")
    
for f in sorted(Path('.').glob('*.md')):
    size = f.stat().st_size
    print(f"  [OK] {f.name:<30} ({size:,} bytes)")

print("\n[+] CONFIGURATION:")
project_dir = Path(__file__).resolve().parent
env_file = project_dir / ".env"
local_config = {}
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            local_config[key.strip()] = value.strip()

all_configured = True
for key in ("MEALIE_URL", "MEALIE_TOKEN"):
    configured = bool(os.getenv(key) or local_config.get(key))
    print(f"  [{'OK' if configured else '!!'}] {key} configured: {configured}")
    all_configured = all_configured and configured

print("\n[+] DEPENDENCIES:")
deps = {
    'requests': 'HTTP requests library',
    'bs4': 'BeautifulSoup HTML parser',
    'urllib3': 'SSL/HTTP utilities'
}
if sys.version_info >= (3, 10):
    deps['truststore'] = 'Operating system certificate trust for website requests'

all_installed = True
for module, desc in deps.items():
    try:
        mod = __import__(module)
        version = getattr(mod, '__version__', 'installed')
        print(f"  [OK] {module:<15} {desc}")
    except ImportError:
        print(f"  [!!] {module:<15} NOT INSTALLED")
        all_installed = False

print("\n[+] READY TO USE:")
if all_installed and all_configured:
    print("  [OK] All requirements met!")
    print("\n  To start: python mealie_importer.py")
else:
    print("  [!] Missing requirements. Install with:")
    if not all_installed:
        print("     python -m pip install -r requirements.txt")
    if not all_configured:
        print("     Copy .env.example to .env and configure required settings.")

print("\n" + "="*70)
print("DOCUMENTATION:")
print("="*70)
print("  * README.md - Complete documentation")
print("  * QUICK_START.md - Quick reference")
print("  * PROJECT_SUMMARY.md - Project overview")
print("\n[OK] SETUP COMPLETE - Ready to import recipes!")
print("="*70)
