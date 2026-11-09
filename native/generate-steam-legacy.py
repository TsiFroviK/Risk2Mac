#!/usr/bin/env python3
"""Generate C wrappers against the user's matching legacy Steamworks headers."""
import argparse
from pathlib import Path
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--sdk", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
flat = (args.sdk / "steam_api_flat.h").read_text(encoding="utf-8-sig")
interfaces = "\n".join(path.read_text(encoding="latin1") for path in args.sdk.glob("isteam*.h"))
output = [
    '// Generated locally from the supplied legacy SDK headers.',
    '#include <stdint.h>',
    '#include "steam_api.h"',
    '#include "steam_gameserver.h"',
    'template<class T> T convert_return(T value) { return value; }',
    'static uint64 convert_return(CSteamID value) { return value.ConvertToUint64(); }',
    'static uint64 convert_return(CGameID value) { return value.ToUint64(); }',
]
for match in re.finditer(r'^S_API\s+(.+?)\s+(SteamAPI_(ISteam\w+?)_(\w+))\((.*?)\);', flat, re.M):
    result, symbol, interface, method, parameters = match.groups()
    names = [re.search(r'(\w+)(?:\[.*\])?$', item.strip()).group(1) for item in parameters.split(',')]
    actual = method
    if not re.search(r'\b' + re.escape(method) + r'\s*\(', interfaces):
        actual = re.sub(r'\d+$', '', method)
    if actual.startswith('Destruct'):
        call = f'reinterpret_cast<{interface} *>(instancePtr)->~{interface}()'
    else:
        call = f'reinterpret_cast<{interface} *>(instancePtr)->{actual}(' + ', '.join(names[1:]) + ')'
    expression = f'return {call};' if result == 'void' else f'return convert_return({call});'
    output.append(f'extern "C" {result} Risk2MacLegacy_{symbol}({parameters}) {{ {expression} }}')
args.output.write_text('\n'.join(output) + '\n', encoding='utf-8')
print(f'Generated {len(output) - 8} legacy Steam wrappers')
