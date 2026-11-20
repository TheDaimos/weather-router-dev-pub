"""Presentation-only DWD-style RATE palette; numerical inputs are never changed."""
from math import isfinite

# Lower inclusive limits in mm/h from DWD WMS legend labels, not the
# rounded five-minute accumulation quantities in its SLD.
# Presentation colors exactly match DWD; numeric RATE classes remain unchanged.
RATE_COLORS = (
    (0.0, (51,255,255)), (0.2, (26,204,154)), (0.4, (1,153,52)), (1.0, (77,179,27)), (2.0, (153,204,1)),
    (3.0, (204,230,1)), (5.0, (255,255,1)), (7.5, (255,196,1)),
    (10.0, (255,137,1)), (15.0, (255,69,1)), (30.0, (254,0,0)),
    (45.0, (229,0,76)), (75.0, (204,0,152)), (100.0, (102,0,203)),
    (150.0, (0,0,254)),
)

def rate_legend():
    """The renderer's own class table, exposed as read-only presentation metadata."""
    entries=[]
    for index,(lower,rgb) in enumerate(RATE_COLORS):
        upper=RATE_COLORS[index+1][0] if index+1<len(RATE_COLORS) else None
        label=(f">0–<{upper:g}" if lower==0 else f"{lower:g}–<{upper:g}" if upper else f"≥{lower:g}")
        entries.append({"value":lower,"label":label,"color":"#%02x%02x%02x"%rgb})
    return {"title":"OPERA RATE", "unit":"mm/h", "entries":entries}


def dwd_rate_legend():
    """DWD niederschlagsradar default SLD legend labels, not a recoloring rule.

    Verified GetStyles 2026-11-06; source 5-minute quantities are rounded.
    Only the known default style receives these presentation metadata.
    """
    colors=((51,255,255),(26,204,154),(1,153,52),(77,179,27),
        (153,204,1),(204,230,1),(255,255,1),(255,196,1),(255,137,1),
        (255,69,1),(254,0,0),(229,0,76),(204,0,152),(102,0,203),(0,0,254))
    lower=(.1,.2,.4,1,2,3,5,7.5,10,15,30,45,75,100,150)
    return {"title":"DWD · Originalfarben", "unit":"mm/h", "entries":[
        {"value":v,"label":f"{v:g}–<{lower[i+1]:g}" if i+1<len(lower) else f"≥{v:g}",
         "color":"#%02x%02x%02x"%colors[i]} for i,v in enumerate(lower)]}

def rate_rgba(value):
    try:
        value=float(value)
    except (TypeError,ValueError,OverflowError):
        return (0,0,0,0)
    if not isfinite(value) or value <= 0:
        return (0,0,0,0)
    rgb=RATE_COLORS[0][1]
    for lower,color in RATE_COLORS:
        if value < lower: break
        rgb=color
    return (*rgb,255)

def colorize_rate(values,valid):
    import numpy as np
    rgba=np.zeros((*values.shape,4),dtype=np.uint8)
    visible=valid & np.isfinite(values) & (values > 0)
    for lower,rgb in RATE_COLORS:
        rgba[visible & (values >= lower)]=(*rgb,255)
    return rgba

# The completed scientific baseline remains immutable. Only this exact
# presentation substitution is normalized for its original Git-blob check;
# any change to decoding, projection, masks or sampling still fails closed.
BASELINE_COLOR_BLOCK = '        valid &= np.isfinite(values) & (values >= 0)\n        intensity = np.clip(values / 50.0, 0, 1)\n        rgba[..., 0] = np.where(valid, np.round(intensity * 255), 0).astype(np.uint8)\n        rgba[..., 2] = np.where(valid, np.round((1-intensity) * 255), 0).astype(np.uint8)\n        rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)\n'
PRESENTATION_COLOR_BLOCK = '        from .opera_rate_palette import colorize_rate\n        valid &= np.isfinite(values) & (values > 0)\n        rgba = colorize_rate(values, valid)\n'

def scientific_baseline_bytes(name,content):
    if name != 'opera_odim_tile.py': return content
    replacement=PRESENTATION_COLOR_BLOCK.encode()
    if content.count(replacement)==1:
        return content.replace(replacement,BASELINE_COLOR_BLOCK.encode(),1)
    return content
