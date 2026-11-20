"""Native legend metadata, losslessly extracted from the GIBS-declared GPM colormap.
No numeric precipitation or snow-depth conversion; no embedded image or URL navigation.
"""
from pathlib import Path
from functools import lru_cache
from copy import deepcopy
import json

@lru_cache(maxsize=1)
def _source():
    return json.loads((Path(__file__).parent/'data/gpm_precipitation_rate_legend.json').read_text(encoding='utf-8'))

def imerg_native_legend():
    data=_source()
    return {"title":"NASA IMERG · Originalskalen", "scales":deepcopy(data['scales']),
            "colormap_source":data['source_url'],"colormap_sha256":data['source_sha256']}
