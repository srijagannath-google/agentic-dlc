#!/usr/bin/env python3
"""Official Google Cloud Reference Style Architecture Diagram SVG/PNG Renderer & Validator.

Uses the visual grammar of `resources/reference_gcp_architecture_diagram.png`:
- Royal Google Blue (#1A73E8) outer 'Google Cloud' banner frame with white (#FFFFFF) interior canvas
- Alternating neutral gray (#F1F3F4) and soft Google Blue (#AECBFA) concentric zone/VPC/subnet containers
- Dashed perimeter groupings (#5F6368, stroke-dasharray 4,4)
- Crisp white rounded product/component cards (#FFFFFF, stroke #3C4043) with official 4-color Google Cloud icons
- Orthogonal charcoal (#202124), red dashed (#D93025), and amber (#F29900) connectors

Crucially, this renderer is application-specific (NEVER a static networking boilerplate copy) and derives its
Google Cloud Reference SVG/PNG directly from the Mermaid `flowchart LR` blocks in `design/architecture_design.md`
(so no raw JSON blocks pollute the Markdown document):
- Diagram 1 (`logical_architecture`): Renders the application's Business Personas in the left column,
  User Experience Channels & Data Privacy Gateway in Column 1, Role-Based Access Control + Lifecycle Workflow
  Engine + Business Rules Engine in Column 2, and Business Capability Services + Logical Domain Data Stores
  in the Column 3 3x3 grid.
- Diagram 2 (`technical_architecture`): Renders the application's External Clients / IdP / Hybrid Gateway on the left,
  Cloud Load Balancing + Cloud Armor + Cloud CDN + Identity-Aware Proxy in Column 1, Multi-Region Shared VPC with
  Primary & Secondary Region GKE Web & Application Tiers in Column 2, and the 3x3 grid of Managed Database
  (PgBouncer + AlloyDB/Cloud SQL Primary + Read Replica), Cloud Storage + Cloud KMS + Workload Identity, and
  Cloud Logging/Trace + Cloud Monitoring + GDC Config Sync/Policy Controller in Column 3.
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _esc(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


# --------------------------------------------------------------------------- Official Google Cloud Vector Icons (24x24)
def _icon_gateway(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<rect x="1" y="6" width="20" height="12" rx="2.5" fill="#202124"/>'
        f'<circle cx="6.5" cy="12" r="1.3" fill="#FFFFFF"/>'
        f'<circle cx="11" cy="12" r="1.3" fill="#FFFFFF"/>'
        f'<circle cx="15.5" cy="12" r="1.3" fill="#FFFFFF"/>'
        f"</g>"
    )


def _icon_persona(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<circle cx="11" cy="12" r="10" fill="#E8F0FE" stroke="#1A73E8" stroke-width="1.5"/>'
        f'<circle cx="11" cy="9.2" r="3.2" fill="#1A73E8"/>'
        f'<path d="M5.5 18.2 C5.5 14.8 16.5 14.8 16.5 18.2" fill="#1A73E8"/>'
        f"</g>"
    )


def _icon_ui(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<rect x="2" y="3" width="18" height="16" rx="2" fill="#FFFFFF" stroke="#1967D2" stroke-width="1.5"/>'
        f'<rect x="2" y="3" width="18" height="4.5" rx="1.5" fill="#4285F4"/>'
        f'<rect x="4.5" y="10" width="5.5" height="6.5" rx="1" fill="#34A853"/>'
        f'<rect x="11.5" y="10" width="6" height="2.8" rx="0.8" fill="#FBBC04"/>'
        f'<rect x="11.5" y="13.8" width="6" height="2.7" rx="0.8" fill="#EA4335"/>'
        f"</g>"
    )


def _icon_security(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<path d="M11 2.5 L19 5.8 L19 11.8 C19 16.5 15.6 19.9 11 21.5 C6.4 19.9 3 16.5 3 11.8 L3 5.8 Z" '
        f'fill="#E8F0FE" stroke="#1967D2" stroke-width="1.6"/>'
        f'<path d="M11 4.2 L17.3 6.8 L17.3 11.6 C17.3 15.4 14.6 18.2 11 19.6 Z" fill="#4285F4" opacity="0.25"/>'
        f'<path d="M7.8 12.2 L10.1 14.5 L14.6 9.5" fill="none" stroke="#1E8E3E" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        f"</g>"
    )


def _icon_workflow(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<rect x="2" y="3" width="6.5" height="5" rx="1.2" fill="#4285F4"/>'
        f'<polygon points="15.5,2.5 20.5,6 15.5,9.5 10.5,6" fill="#FBBC04" stroke="#E37400" stroke-width="1"/>'
        f'<rect x="12" y="14.5" width="7.5" height="5.5" rx="1.2" fill="#34A853"/>'
        f'<rect x="2" y="14.5" width="6.5" height="5.5" rx="1.2" fill="#EA4335"/>'
        f'<path d="M8.5 5.8 L10.5 5.8 M15.5 9.5 L15.5 14.5 M10.5 6 L5.2 14.5" fill="none" stroke="#3C4043" stroke-width="1.3"/>'
        f"</g>"
    )


def _icon_rules(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<rect x="2.5" y="3" width="17" height="18" rx="2" fill="#FFFFFF" stroke="#1967D2" stroke-width="1.5"/>'
        f'<line x1="6" y1="7.5" x2="16" y2="7.5" stroke="#4285F4" stroke-width="2" stroke-linecap="round"/>'
        f'<line x1="6" y1="12" x2="16" y2="12" stroke="#34A853" stroke-width="2" stroke-linecap="round"/>'
        f'<line x1="6" y1="16.5" x2="13" y2="16.5" stroke="#FBBC04" stroke-width="2" stroke-linecap="round"/>'
        f'<circle cx="16" cy="16.5" r="1.4" fill="#EA4335"/>'
        f"</g>"
    )


def _icon_database(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<ellipse cx="11" cy="5.5" rx="7.5" ry="2.8" fill="#E8F0FE" stroke="#1967D2" stroke-width="1.5"/>'
        f'<path d="M3.5 5.5 L3.5 11.5 C3.5 13.1 6.9 14.3 11 14.3 C15.1 14.3 18.5 13.1 18.5 11.5 L18.5 5.5" fill="#E8F0FE" stroke="#1967D2" stroke-width="1.5"/>'
        f'<path d="M3.5 11.5 L3.5 17.5 C3.5 19.1 6.9 20.3 11 20.3 C15.1 20.3 18.5 19.1 18.5 17.5 L18.5 11.5" fill="#E8F0FE" stroke="#1967D2" stroke-width="1.5"/>'
        f'<circle cx="15" cy="10.2" r="1.2" fill="#34A853"/>'
        f'<circle cx="15" cy="16.2" r="1.2" fill="#34A853"/>'
        f"</g>"
    )


def _icon_storage(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<path d="M3 6.5 L8.5 6.5 L10.5 8.5 L19 8.5 L19 18.5 L3 18.5 Z" fill="#E8F0FE" stroke="#1967D2" stroke-width="1.5"/>'
        f'<rect x="6" y="11" width="10" height="2" rx="0.8" fill="#4285F4"/>'
        f'<rect x="6" y="14.2" width="7" height="2" rx="0.8" fill="#FBBC04"/>'
        f"</g>"
    )


def _icon_observability(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<rect x="2" y="3" width="18" height="16" rx="2" fill="#FFFFFF" stroke="#1967D2" stroke-width="1.5"/>'
        f'<polyline points="4,14 8,10 11,13 15,7 18,9" fill="none" stroke="#34A853" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="15" cy="7" r="1.6" fill="#4285F4"/>'
        f"</g>"
    )


def _icon_gcp_network(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})" stroke="#4285F4" stroke-width="1.6" fill="none">'
        f'<line x1="11" y1="3" x2="11" y2="21" stroke="#1967D2" stroke-width="1.8"/>'
        f'<line x1="5" y1="7" x2="17" y2="7"/>'
        f'<line x1="5" y1="17" x2="17" y2="17"/>'
        f'<circle cx="4" cy="7" r="2.3" fill="#FFFFFF" stroke="#4285F4" stroke-width="1.5"/>'
        f'<circle cx="18" cy="7" r="2.3" fill="#FFFFFF" stroke="#4285F4" stroke-width="1.5"/>'
        f'<circle cx="4" cy="17" r="2.3" fill="#FFFFFF" stroke="#4285F4" stroke-width="1.5"/>'
        f'<circle cx="18" cy="17" r="2.3" fill="#FFFFFF" stroke="#4285F4" stroke-width="1.5"/>'
        f'<circle cx="11" cy="12" r="2.6" fill="#4285F4" stroke="#1967D2" stroke-width="1.2"/>'
        f"</g>"
    )


def _icon_gcp_compute_chip(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<rect x="6" y="1" width="2.2" height="4" fill="#4285F4"/>'
        f'<rect x="10.9" y="1" width="2.2" height="4" fill="#4285F4"/>'
        f'<rect x="15.8" y="1" width="2.2" height="4" fill="#4285F4"/>'
        f'<rect x="1" y="6" width="4" height="2.2" fill="#4285F4"/>'
        f'<rect x="1" y="10.9" width="4" height="2.2" fill="#4285F4"/>'
        f'<rect x="1" y="15.8" width="4" height="2.2" fill="#4285F4"/>'
        f'<rect x="6" y="19" width="2.2" height="4" fill="#FBBC04"/>'
        f'<rect x="10.9" y="19" width="2.2" height="4" fill="#FBBC04"/>'
        f'<rect x="15.8" y="19" width="2.2" height="4" fill="#FBBC04"/>'
        f'<rect x="19" y="6" width="4" height="2.2" fill="#EA4335"/>'
        f'<rect x="19" y="10.9" width="4" height="2.2" fill="#EA4335"/>'
        f'<rect x="19" y="15.8" width="4" height="2.2" fill="#EA4335"/>'
        f'<path d="M5,5 L19,5 L19,12 L5,12 Z" fill="none" stroke="#4285F4" stroke-width="1.6"/>'
        f'<path d="M5,12 L12,12 L12,19 L5,19 Z" fill="none" stroke="#FBBC04" stroke-width="1.6"/>'
        f'<path d="M12,12 L19,12 L19,19 L12,19 Z" fill="none" stroke="#EA4335" stroke-width="1.6"/>'
        f'<rect x="5" y="5" width="14" height="14" rx="1.5" fill="#FFFFFF" stroke="#4285F4" stroke-width="1.4"/>'
        f'<rect x="8.2" y="8.2" width="7.6" height="7.6" rx="1" fill="none" stroke="#34A853" stroke-width="1.8"/>'
        f"</g>"
    )


def _render_icon(kind: str, x: float, y: float) -> str:
    k = (kind or "compute").lower()
    if k == "gateway":
        return _icon_gateway(x, y)
    if k in ("persona", "actor", "user"):
        return _icon_persona(x, y)
    if k in ("ui", "portal", "frontend"):
        return _icon_ui(x, y)
    if k in ("security", "iam", "waf", "kms", "shield"):
        return _icon_security(x, y)
    if k in ("workflow", "state"):
        return _icon_workflow(x, y)
    if k in ("rules", "formula", "policy"):
        return _icon_rules(x, y)
    if k in ("database", "db", "sql", "alloydb"):
        return _icon_database(x, y)
    if k in ("storage", "vault", "bucket", "document"):
        return _icon_storage(x, y)
    if k in ("observability", "otel", "monitoring", "gitops"):
        return _icon_observability(x, y)
    if k in ("network", "interconnect", "router", "lb", "vpc"):
        return _icon_gcp_network(x, y)
    return _icon_gcp_compute_chip(x, y)


def _white_product_card(
    x: float,
    y: float,
    w: float,
    h: float,
    line1: str,
    line2: str = "",
    line3: str = "",
    icon_kind: str = "compute",
    bold_line1: bool = True,
) -> str:
    """Renders a crisp white Google Cloud product/component card (#FFFFFF, stroke #3C4043, rx=4)."""
    icon_x = x + 4.5
    icon_y = y + (h - 24) / 2
    text_x = x + 28.5
    narrow = w < 105
    char_px = 4.0 if narrow else 4.35
    max_chars = max(13, int((w - 30) / char_px))

    def _fit(s: str, limit: int) -> str:
        s = str(s or "").strip()
        return s if len(s) <= limit else s[: limit - 1] + "…"

    l1 = _fit(line1, max_chars)
    l2 = _fit(line2, max_chars + 2)
    l3 = _fit(line3, max_chars + 2)

    parts = [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4" '
        f'fill="#FFFFFF" stroke="#3C4043" stroke-width="1.25"/>',
        _render_icon(icon_kind, icon_x, icon_y),
    ]
    fw1 = "600" if bold_line1 else "500"
    if narrow:
        fs1 = "7.8" if len(l1) > 14 else "8.2"
        fs2 = "7.0" if len(l2) > 15 else "7.3"
    else:
        fs1 = "8.2" if len(l1) > 18 else "8.8"
        fs2 = "7.3" if len(l2) > 20 else "7.8"
    if l1 and not l2 and not l3:
        parts.append(
            f'<text x="{text_x:.1f}" y="{y + h / 2 + 3.5:.1f}" font-size="{fs1}" font-weight="{fw1}" fill="#202124">'
            f"{_esc(l1)}</text>"
        )
    elif l1 and l2 and not l3:
        parts.append(
            f'<text x="{text_x:.1f}" y="{y + h / 2 - 2.5:.1f}" font-size="{fs1}" font-weight="{fw1}" fill="#202124">'
            f"{_esc(l1)}</text>"
        )
        parts.append(
            f'<text x="{text_x:.1f}" y="{y + h / 2 + 8.5:.1f}" font-size="{fs2}" font-weight="400" fill="#3C4043">'
            f"{_esc(l2)}</text>"
        )
    else:
        parts.append(
            f'<text x="{text_x:.1f}" y="{y + h / 2 - 7.5:.1f}" font-size="8.0" font-weight="600" fill="#202124">'
            f"{_esc(l1)}</text>"
        )
        parts.append(
            f'<text x="{text_x:.1f}" y="{y + h / 2 + 2.0:.1f}" font-size="7.2" font-weight="400" fill="#3C4043">'
            f"{_esc(l2)}</text>"
        )
        parts.append(
            f'<text x="{text_x:.1f}" y="{y + h / 2 + 11.0:.1f}" font-size="7.0" font-weight="400" fill="#5F6368">'
            f"{_esc(l3)}</text>"
        )
    return "\n".join(parts)


def render_gcp_reference_svg(spec: dict[str, Any]) -> str:
    """Renders an application-specific Google Cloud Reference Style SVG from a `gcp-arch-diagram` dict.

    The layout is derived from the diagram itself: N persona/client cards on the left, M edge cards in column 1,
    R stacked regions inside the hub container and an r x c spoke grid on the right. Nothing is truncated and no
    placeholder card is invented — the canvas simply grows (the classic 4 / 2 / 3x3 reference layout renders at
    exactly 1320x500 as before).
    """
    on_prem = spec.get("onPremises") or {}
    on_prem_lines = on_prem.get("titleLines") or ["External Tier", ""]
    # Support either a list of `cards` (persona/client cards) or a single `gatewayCard`
    left_cards: list[dict[str, Any]] = list(on_prem.get("cards") or [])
    if not left_cards and on_prem.get("gatewayCard"):
        left_cards = [on_prem["gatewayCard"]]

    cloud_title = spec.get("cloudTitle") or "Enterprise Target Platform"
    adv_route = spec.get("advertisedRoute")  # None when the Mermaid source has no dashed ('-.->') connector
    edge_cards = list(spec.get("edgeCards") or [])
    hub = spec.get("hubProject") or {}
    hub_title = hub.get("title") or ""
    vpc_title = hub.get("vpcTitle") or ""
    regions = list(hub.get("regions") or [])
    spoke_rows = [list(r or []) for r in (spec.get("spokeRows") or [])]
    n_cols = max((len(r) for r in spoke_rows), default=0)
    n_rows = len(spoke_rows)

    # ---------------------------------------------------------------- geometry (derived from counts)
    n_left = len(left_cards)
    if n_left <= 1:
        left_gap, left_h, left_start = 74, 48, 68
    elif n_left <= 4:
        left_gap, left_h, left_start = 74, 52, 66
    else:
        left_gap, left_h, left_start = 62, 48, 66
    left_bottom = left_start + (n_left - 1) * left_gap + left_h if n_left else 60

    EDGE_GAP, EDGE_H = 78, 52
    edge_ys = [118 + i * EDGE_GAP for i in range(len(edge_cards))]
    edge_bottom = (edge_ys[-1] + EDGE_H) if edge_ys else 118

    REGION_GAP, REGION_H = 128, 118
    n_reg = len(regions)
    region_ys = [162 + i * REGION_GAP for i in range(n_reg)]
    vpc_y = 136
    vpc_h = 26 + REGION_GAP * max(n_reg, 1)
    proj_y = 108
    proj_h = vpc_h + 42
    perim_y = 96
    perim_h = proj_h + 32
    hub_bottom = perim_y + perim_h
    hub_mid = (region_ys[0] + (region_ys[-1] + REGION_H - region_ys[0]) / 2) if region_ys else (vpc_y + vpc_h / 2)

    COL_W, ROW_H = 168, 124
    col_xs = [778 + c * COL_W for c in range(n_cols)]
    row_ys = [84 + r * ROW_H for r in range(n_rows)]
    spoke_w = 12 + COL_W * max(n_cols, 1)
    spoke_h = 16 + ROW_H * max(n_rows, 1)
    spoke_bottom = 72 + spoke_h

    width = max(1320, 766 + spoke_w + 38)
    height = max(500, int(max(left_bottom + 36, edge_bottom + 40, hub_bottom + 40, spoke_bottom + 40)))
    frame_h = height - 36
    inner_h = height - 80

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        'font-family="\'Google Sans\', \'Roboto\', \'Inter\', -apple-system, BlinkMacSystemFont, \'Segoe UI\', Arial, sans-serif">',
        "<defs>",
        '  <marker id="arrowDark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5" fill="none" stroke="#202124" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
        "  </marker>",
        '  <marker id="arrowRed" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5" fill="none" stroke="#D93025" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
        "  </marker>",
        '  <marker id="arrowAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5" fill="none" stroke="#F29900" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
        "  </marker>",
        "</defs>",
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#FFFFFF"/>',
        # 1. Left Container (#F1F3F4)
        f'<rect x="16" y="18" width="136" height="{frame_h}" rx="4" fill="#F1F3F4" stroke="#9AA0A6" stroke-width="1.2"/>',
        f'<text x="84" y="38" text-anchor="middle" font-size="11" font-weight="500" fill="#3C4043">{_esc(on_prem_lines[0])}</text>',
        f'<text x="84" y="52" text-anchor="middle" font-size="10.5" font-weight="400" fill="#5F6368">{_esc(on_prem_lines[1] if len(on_prem_lines) > 1 else "")}</text>',
    ]

    # Render every persona/client card inside the Left Container
    left_card_positions: list[tuple[float, float]] = []
    if n_left == 1:
        lc = left_cards[0]
        svg.append(
            _white_product_card(
                25, 68, 118, 48,
                lc.get("line1", ""), lc.get("line2", ""), lc.get("line3", ""),
                icon_kind=lc.get("icon", "gateway"), bold_line1=True,
            )
        )
        left_card_positions.append((25, 68))
    else:
        for idx, lc in enumerate(left_cards):
            cy = left_start + idx * left_gap
            svg.append(
                _white_product_card(
                    24, cy, 120, left_h,
                    lc.get("line1", ""), lc.get("line2", ""), lc.get("line3", ""),
                    icon_kind=lc.get("icon", "persona"), bold_line1=True,
                )
            )
            left_card_positions.append((24, cy))

    # 2. Right Outer Frame: Google Cloud (#1A73E8 banner + white interior canvas)
    svg += [
        f'<rect x="168" y="18" width="{width - 184}" height="{frame_h}" rx="3" fill="#1A73E8" stroke="#1A73E8" stroke-width="2"/>',
        f'<text x="184" y="42" font-size="17" font-weight="500" fill="#FFFFFF">{_esc(cloud_title)}</text>',
        f'<rect x="176" y="54" width="{width - 200}" height="{inner_h}" rx="2" fill="#FFFFFF"/>',
    ]

    # 3. Column 1 Inside Frame: stacked cards (UI Workspaces in §1, Edge Security/Ingress in §2)
    for ec, cy in zip(edge_cards, edge_ys):
        svg.append(
            _white_product_card(
                196, cy, 122, EDGE_H,
                ec.get("line1", ""), ec.get("line2", ""), ec.get("line3", ""),
                icon_kind=ec.get("icon", "ui"),
            )
        )
    edge_mids = [cy + EDGE_H / 2 for cy in edge_ys]

    # Orthogonal Bus connecting Left Column Cards <-> Column 1 Cards -> Column 2 Hub Core
    left_mids = [cy + (24 if n_left == 1 else 25) for _, cy in left_card_positions]
    if n_left == 1 and edge_mids:
        svg.append(
            f'<path d="M 84 {left_card_positions[0][1] + 48} L 84 {edge_mids[0]:.1f} L 182 {edge_mids[0]:.1f}" fill="none" stroke="#202124" stroke-width="1.3" marker-start="url(#arrowDark)"/>'
        )
    else:
        for mid_y in left_mids:
            svg.append(f'<line x1="144" y1="{mid_y:.1f}" x2="182" y2="{mid_y:.1f}" stroke="#202124" stroke-width="1.2"/>')
    bus_ys = left_mids + edge_mids
    if bus_ys:
        svg.append(f'<line x1="182" y1="{min(bus_ys):.1f}" x2="182" y2="{max(bus_ys):.1f}" stroke="#202124" stroke-width="1.3"/>')
    for my in edge_mids:
        svg.append(f'<line x1="182" y1="{my:.1f}" x2="194" y2="{my:.1f}" stroke="#202124" stroke-width="1.3" marker-end="url(#arrowDark)"/>')
        svg.append(f'<line x1="318" y1="{my:.1f}" x2="332" y2="{my:.1f}" stroke="#202124" stroke-width="1.3"/>')
    if edge_mids:
        svg.append(f'<line x1="332" y1="{min(edge_mids + [hub_mid]):.1f}" x2="332" y2="{max(edge_mids + [hub_mid]):.1f}" stroke="#202124" stroke-width="1.3"/>')
    svg.append(f'<line x1="332" y1="{hub_mid:.1f}" x2="356" y2="{hub_mid:.1f}" stroke="#202124" stroke-width="1.3"/>')

    # 4. Column 2: Dashed Hub Perimeter + Stacked Project Container (#F1F3F4) + Nested Blue Container (#AECBFA)
    svg += [
        f'<rect x="344" y="{perim_y}" width="398" height="{perim_h}" rx="3" fill="none" stroke="#5F6368" stroke-width="1.2" stroke-dasharray="4,4"/>',
        f'<rect x="364" y="{proj_y + 8}" width="366" height="{proj_h}" rx="4" fill="#F1F3F4" stroke="#7F868D" stroke-width="1.1"/>',
        f'<rect x="360" y="{proj_y + 4}" width="366" height="{proj_h}" rx="4" fill="#F1F3F4" stroke="#7F868D" stroke-width="1.1"/>',
        f'<rect x="356" y="{proj_y}" width="366" height="{proj_h}" rx="4" fill="#F1F3F4" stroke="#5F6368" stroke-width="1.3"/>',
        f'<text x="539" y="{proj_y + 18.5}" text-anchor="middle" font-size="{"9.5" if len(hub_title) > 48 else "11.0"}" font-weight="500" fill="#202124">{_esc(hub_title)}</text>',
        f'<rect x="368" y="{vpc_y}" width="342" height="{vpc_h}" rx="4" fill="#AECBFA" stroke="#4285F4" stroke-width="1.2"/>',
        f'<text x="539" y="{vpc_y + 17}" text-anchor="middle" font-size="{"9.8" if len(vpc_title) > 44 else "10.8"}" font-weight="500" fill="#202124">{_esc(vpc_title)}</text>',
    ]

    for r_idx, reg in enumerate(regions):
        ry = region_ys[r_idx]
        card_y = ry + 42
        sub_y = ry + 18
        r_router = reg.get("router")
        r_lb = reg.get("loadBalancer")
        r_wk = reg.get("workload")
        has_subnet = bool(reg.get("subnetTitle") or r_wk)
        svg += [
            f'<rect x="378" y="{ry}" width="322" height="{REGION_H}" rx="4" fill="#F1F3F4" stroke="#7F868D" stroke-width="1.1"/>',
            f'<text x="388" y="{ry + 15.5}" text-anchor="start" font-size="9.0" font-weight="500" fill="#3C4043">{_esc(reg.get("title", ""))}</text>',
        ]
        if r_router:
            svg.append(_white_product_card(386, card_y, 92, 52, r_router.get("line1", ""), r_router.get("line2", ""), r_router.get("line3", ""),
                                           icon_kind=r_router.get("icon", "network")))
        if r_lb:
            svg.append(_white_product_card(484, card_y, 94, 52, r_lb.get("line1", ""), r_lb.get("line2", ""), r_lb.get("line3", ""),
                                           icon_kind=r_lb.get("icon", "network")))
        if has_subnet:
            svg += [
                f'<rect x="586" y="{sub_y}" width="106" height="90" rx="4" fill="#AECBFA" stroke="#4285F4" stroke-width="1.1"/>',
                f'<text x="639" y="{sub_y + 15}" text-anchor="middle" font-size="9.5" font-weight="500" fill="#202124">{_esc(reg.get("subnetTitle", ""))}</text>',
            ]
        if r_wk:
            svg.append(_white_product_card(592, card_y, 94, 52, r_wk.get("line1", ""), r_wk.get("line2", ""), r_wk.get("line3", ""),
                                           icon_kind=r_wk.get("icon", "compute"), bold_line1=True))
        if r_router and r_lb:
            svg.append(f'<line x1="478" y1="{card_y + 26}" x2="484" y2="{card_y + 26}" stroke="#202124" stroke-width="1.3"/>')
        if r_lb and r_wk:
            svg.append(f'<line x1="578" y1="{card_y + 26}" x2="592" y2="{card_y + 26}" stroke="#202124" stroke-width="1.3"/>')

    # 5. Red Dashed Guard / Route Advertisement Path (#D93025) — only when the diagram declares a dashed connector
    if adv_route:
        red_target_x = 146 if n_left > 1 else 145
        red_start_y = (region_ys[0] + 42) if region_ys else (vpc_y + 20)
        svg += [
            f'<path d="M 432 {red_start_y} L 432 88 L {red_target_x} 88" fill="none" stroke="#D93025" stroke-width="1.4" stroke-dasharray="5,4" marker-end="url(#arrowRed)"/>',
            f'<text x="262" y="65" text-anchor="middle" font-size="8.3" font-weight="600" fill="#D93025">{_esc(adv_route.get("line1", ""))}</text>',
            f'<text x="262" y="74.5" text-anchor="middle" font-size="8.2" font-weight="500" fill="#202124">{_esc(adv_route.get("line2", ""))}</text>',
            f'<text x="262" y="84" text-anchor="middle" font-size="8.0" font-weight="400" fill="#3C4043">{_esc(adv_route.get("line3", ""))}</text>',
        ]

    # 6. Column 3: Dashed Spoke / Capability Grid Perimeter + r x c Matrix + Amber (#F29900) Bus
    svg.append(
        f'<rect x="766" y="72" width="{spoke_w}" height="{spoke_h}" rx="3" fill="none" stroke="#5F6368" stroke-width="1.2" stroke-dasharray="4,4"/>'
    )

    for r_idx, row in enumerate(spoke_rows):
        ry = row_ys[r_idx]
        for c_idx, cell in enumerate(row):
            if not cell:
                continue  # ragged row — leave the slot empty rather than inventing a card
            cx = col_xs[c_idx]
            tlines = cell.get("titleLines") or ["", ""]
            card = cell.get("card") or {}
            box_fill = cell.get("containerFill") or "#F1F3F4"
            box_stroke = cell.get("containerStroke") or "#9AA0A6"
            svg += [
                f'<rect x="{cx}" y="{ry}" width="156" height="114" rx="4" fill="{box_fill}" stroke="{box_stroke}" stroke-width="1.2"/>',
                f'<text x="{cx + 78}" y="{ry + 17}" text-anchor="middle" font-size="9.8" font-weight="500" fill="#202124">{_esc(tlines[0])}</text>',
                f'<text x="{cx + 78}" y="{ry + 29}" text-anchor="middle" font-size="9.0" font-weight="400" fill="#3C4043">{_esc(tlines[1] if len(tlines) > 1 else "")}</text>',
                _white_product_card(
                    cx + 14, ry + 40, 128, 58,
                    card.get("line1", ""), card.get("line2", ""), card.get("line3", ""),
                    icon_kind=card.get("icon", "compute"),
                ),
            ]

    # Amber bus drawn on top so arrowheads cleanly reach each row's first card (x=790)
    if row_ys:
        arrow_ys = [ry + 69 for ry in row_ys]
        svg += [
            f'<line x1="710" y1="{hub_mid:.1f}" x2="750" y2="{hub_mid:.1f}" stroke="#F29900" stroke-width="1.6"/>',
            f'<line x1="750" y1="{min(arrow_ys + [hub_mid]):.1f}" x2="750" y2="{max(arrow_ys + [hub_mid]):.1f}" stroke="#F29900" stroke-width="1.6"/>',
        ]
        for ay in arrow_ys:
            svg.append(f'<line x1="750" y1="{ay}" x2="790" y2="{ay}" stroke="#F29900" stroke-width="1.6" marker-end="url(#arrowAmber)"/>')

    svg.append("</svg>")
    return "\n".join(svg) + "\n"


def _split_two_lines(text: str, max_len: int = 20) -> list[str]:
    """Splits a container title into two balanced lines for 156px spoke boxes or 136px left column."""
    t = html.unescape(re.sub(r"<[^>]+>", "", str(text or ""))).strip()
    if not t:
        return ["", ""]
    if len(t) <= max_len:
        return [t, ""]
    words = t.split()
    if len(words) == 1:
        return [t[:max_len], t[max_len : max_len * 2]]
    mid = len(t) // 2
    best_idx = 1
    best_dist = 999
    cur = 0
    for idx, w in enumerate(words[:-1], start=1):
        cur += len(w) + (1 if idx > 1 else 0)
        dist = abs(cur - mid)
        if dist < best_dist:
            best_dist = dist
            best_idx = idx
    return [" ".join(words[:best_idx]), " ".join(words[best_idx:])]


def _infer_card_icon(line1: str, line2: str, zone: str, is_logical: bool) -> str:
    txt = f"{line1} {line2}".lower()
    if zone == "onprem":
        if is_logical:
            return "persona"
        if any(k in txt for k in ("browser", "web", "mobile", "client", "portal", "ui")):
            return "ui"
        if any(k in txt for k in ("idp", "oidc", "saml", "identity", "okta", "entra", "auth")):
            return "security"
        return "gateway"
    if zone == "edge":
        if any(k in txt for k in ("armor", "waf", "iap", "identity", "privacy", "mask", "auth", "shield", "ddos")):
            return "security"
        if any(k in txt for k in ("load balanc", "cdn", "dns", "nat", "router", "interconnect", "anycast")):
            return "network"
        return "ui"
    if zone == "region_router":
        if any(k in txt for k in ("router", "nat", "network", "dns", "interconnect")):
            return "network"
        if any(k in txt for k in ("rbac", "access", "auth", "security", "iam", "role")):
            return "security"
        return "rules"
    if zone == "region_lb":
        if any(k in txt for k in ("workflow", "lifecycle", "state", "orchestrat")):
            return "workflow"
        if any(k in txt for k in ("web", "spa", "ui", "frontend", "react", "angular", "portal", "html")):
            return "ui"
        if any(k in txt for k in ("rule", "calc", "fee", "collateral", "tier", "compliance", "eligib", "accrual", "balance")):
            return "rules"
        return "network"
    if zone == "subnet_workload":
        return "security" if is_logical else "compute"
    if zone == "spoke":
        if any(k in txt for k in ("pgbouncer", "pooler", "load balanc", "vpc", "router", "multiplex")):
            return "network"
        if any(k in txt for k in ("object storage", "s3", "cloud storage", "bucket", "archive", "document store", "certificate store", "vault", "file")):
            return "storage"
        if any(k in txt for k in ("alloydb", "cloud sql", "postgres", "sqlite", "database", "db", "store", "ledger", "repository")):
            return "database"
        if any(k in txt for k in ("kms", "secret", "workload identity", "iam", "encryption", "cmek", "oidc", "hsm")):
            return "security"
        if any(k in txt for k in ("logging", "trace", "tracing", "monitoring", "prometheus", "grafana", "config sync", "otel", "opentelemetry", "observability", "slo", "gitops", "policy")):
            return "observability"
        return "compute"
    return "compute"


def _derive_spoke_cell_header(row_title: str, card_l1: str, card_l2: str, r_idx: int, c_idx: int, is_logical: bool) -> list[str]:
    if "|" in row_title:
        parts = [p.strip() for p in row_title.split("|") if p.strip()]
        if c_idx < len(parts):
            return _split_two_lines(parts[c_idx], max_len=20)
    txt = f"{card_l1} {card_l2}".lower()
    if any(k in txt for k in ("pgbouncer", "pooler", "multiplex")):
        return ["Database Connection", "Pooling Tier"]
    if "primary" in txt and any(k in txt for k in ("db", "sql", "alloy", "postgres", "sqlite", "relational", "cluster")):
        return ["Managed Primary", "Relational DB"]
    if any(k in txt for k in ("replica", "standby", "pitr", "read pool")):
        return ["Cross-Zone Standby", "& Read Replica"]
    if any(k in txt for k in ("object storage", "s3", "cloud storage", "bucket", "vault")):
        return ["Managed Object", "Storage Tier"]
    if any(k in txt for k in ("kms", "secret")):
        return ["Encryption &", "Secrets Management"]
    if any(k in txt for k in ("workload identity", "federated", "keyless")):
        return ["Zero-Trust", "Workload IAM"]
    if any(k in txt for k in ("logging", "trace", "tracing", "otlp", "opentelemetry")):
        return ["Centralized Logging", "& Distributed Trace"]
    if any(k in txt for k in ("monitoring", "prometheus", "slo", "dashboard", "metrics")):
        return ["Metrics, Dashboards", "& SLO Alerting"]
    if any(k in txt for k in ("config sync", "gitops", "policy controller", "policy engine", "gatekeeper", "opa")):
        return ["Multi-Cloud Fleet", "GitOps & Policy"]
    if "audit" in txt and any(k in txt for k in ("store", "archive", "cert", "calendar")):
        return ["Compliance Audit &", "Document Archive"]
    if any(k in txt for k in ("store", "repository", "ledger")):
        return _split_two_lines(card_l1, max_len=20)
    if is_logical:
        if r_idx == 0:
            return ["Core Business", "Capability"]
        if r_idx == 1 and c_idx == 2:
            return ["Shared Business", "Capability"]
        if r_idx == 1:
            return ["Supporting Business", "Capability"]
    return _split_two_lines(row_title, max_len=20)


def parse_mermaid_flowchart_to_spec(mermaid_text: str, diagram_id: str = "logical_architecture") -> dict[str, Any]:
    """Parses a Google Cloud Reference Style Mermaid `flowchart LR` block directly into a renderer spec dict.

    This eliminates the need for any raw JSON blocks inside `design/architecture_design.md`.
    """
    is_logical = "logical" in diagram_id.lower()
    root_children: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    all_sgs: dict[str, dict[str, Any]] = {}
    dashed_label = ""

    for raw_line in mermaid_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        # Match dashed route/rejection edge: A -.->|"..."| B
        dm = re.search(r"-\.->\s*\|\s*\"([^\"]+)\"\s*\||-\.->\s*\|\s*([^|]+)\s*\|", line)
        if dm and not dashed_label:
            dashed_label = html.unescape(dm.group(1) or dm.group(2) or "").strip()
            continue
        # Match subgraph declaration: subgraph ID["Title"] or subgraph ID
        sg_m = re.match(r"^subgraph\s+([A-Za-z0-9_]+)(?:\s*\[\s*\"?(.*?)\"?\s*\])?\s*$", line)
        if sg_m:
            sg_id = sg_m.group(1)
            sg_title = html.unescape(sg_m.group(2) or sg_id).strip()
            sg_node: dict[str, Any] = {"id": sg_id, "title": sg_title, "cards": [], "children": []}
            if stack:
                stack[-1]["children"].append(sg_node)
            else:
                root_children.append(sg_node)
            stack.append(sg_node)
            all_sgs[sg_id.lower()] = sg_node
            continue
        if line == "end":
            if stack:
                stack.pop()
            continue
        # Skip edges, styles, and classDefs
        if any(tok in line for tok in ("-->", "==>", "-.->", "classDef ", "style ")):
            continue
        # Match node card declaration: NODE_ID["<b>Line 1</b><br/>Line 2"]:::gcpCard
        card_m = re.match(r"^([A-Za-z0-9_]+)\s*\[\s*\"(.*?)\"\s*\]", line)
        if card_m and stack:
            raw_label = html.unescape(card_m.group(2))
            parts = [re.sub(r"</?b>", "", p).strip() for p in re.split(r"<br\s*/?>", raw_label, flags=re.IGNORECASE) if p.strip()]
            l1 = parts[0] if parts else card_m.group(1)
            l2 = parts[1] if len(parts) > 1 else ""
            l3 = parts[2] if len(parts) > 2 else ""
            stack[-1]["cards"].append({"id": card_m.group(1), "line1": l1, "line2": l2, "line3": l3})

    def _find_sg(*prefixes: str) -> dict[str, Any] | None:
        for pref in prefixes:
            for k, v in all_sgs.items():
                if k.startswith(pref.lower()):
                    return v
        return None

    onprem_sg = _find_sg("sg_onprem") or (root_children[0] if root_children else {"title": "External Tier", "cards": []})
    cloud_sg = _find_sg("sg_googlecloud") or (root_children[1] if len(root_children) > 1 else {"title": "Google Cloud", "children": []})
    edge_sg = _find_sg("sg_edge") or {"title": "Edge Tier", "cards": []}
    hub_proj_sg = _find_sg("sg_hubproject") or {"title": "", "children": []}
    vpc_sg = _find_sg("sg_sharedvpc") or {"title": "", "children": []}
    # Every SG_Region* subgraph in declaration order (no fixed count of two) — nested in the Shared VPC when present
    region_sgs = [c for c in (vpc_sg.get("children") or []) if str(c.get("id", "")).lower().startswith("sg_region")] \
        or [v for k, v in all_sgs.items() if k.startswith("sg_region")]
    spoke_perim_sg = _find_sg("sg_spokeperimeter") or {"title": "Spoke Grid", "children": []}

    onprem_cards = []
    for c in onprem_sg.get("cards", []):
        onprem_cards.append(
            {
                "line1": c["line1"],
                "line2": c["line2"],
                "line3": c.get("line3", ""),
                "icon": _infer_card_icon(c["line1"], c["line2"], "onprem", is_logical),
                "boldLine1": True,
            }
        )

    edge_cards = []
    for c in edge_sg.get("cards", []):
        edge_cards.append(
            {
                "line1": c["line1"],
                "line2": c["line2"],
                "line3": c.get("line3", ""),
                "icon": _infer_card_icon(c["line1"], c["line2"], "edge", is_logical),
            }
        )

    regions = []
    for r_sg in region_sgs:
        rcards = r_sg.get("cards", [])
        c_router = rcards[0] if len(rcards) > 0 else None
        c_lb = rcards[1] if len(rcards) > 1 else None
        sub_sg = (r_sg.get("children") or [None])[0]
        sub_cards = (sub_sg or {}).get("cards") or []
        c_wk = sub_cards[0] if sub_cards else None
        workload = None
        if c_wk:
            wk_l2 = c_wk.get("line2", "")
            wk_l3 = c_wk.get("line3", "")
            if not wk_l3 and len(wk_l2) > 16 and " " in wk_l2:
                wk_l2, wk_l3 = _split_two_lines(wk_l2, max_len=14)
            workload = {
                "line1": c_wk["line1"],
                "line2": wk_l2,
                "line3": wk_l3,
                "icon": _infer_card_icon(c_wk["line1"], wk_l2, "subnet_workload", is_logical),
            }
        regions.append(
            {
                "title": r_sg.get("title", ""),
                "router": {
                    "line1": c_router["line1"],
                    "line2": c_router["line2"],
                    "icon": _infer_card_icon(c_router["line1"], c_router["line2"], "region_router", is_logical),
                } if c_router else None,
                "loadBalancer": {
                    "line1": c_lb["line1"],
                    "line2": c_lb["line2"],
                    "icon": _infer_card_icon(c_lb["line1"], c_lb["line2"], "region_lb", is_logical),
                } if c_lb else None,
                "subnetTitle": (sub_sg or {}).get("title", ""),
                "workload": workload,
                "cardCount": len(rcards) + len(sub_cards),
            }
        )

    # Parse advertisedRoute / policy rejection label from the dashed edge. None when the diagram has no '-.->'
    # connector so validate_gcp_diagram_spec() can fail meaningfully (no silent default text is rendered).
    adv_route: dict[str, Any] | None
    if "10.240.0.0/16" in dashed_label or "internal.service.mesh" in dashed_label:
        adv_route = {
            "line1": "Private Service Route:",
            "line2": "internal.service.mesh",
            "line3": "10.240.0.0/16",
        }
    elif "199.36.153.4/30" in dashed_label or "restricted.googleapis.com" in dashed_label:
        adv_route = {
            "line1": "Advertised route:",
            "line2": "restricted.googleapis.com",
            "line3": "199.36.153.4/30",
        }
    elif dashed_label:
        if ":" in dashed_label:
            head, tail = dashed_label.split(":", 1)
            l2_part, l3_part = _split_two_lines(tail.strip(), max_len=28)
            adv_route = {
                "line1": head.strip() + ":",
                "line2": l2_part or tail.strip(),
                "line3": l3_part,
            }
        else:
            l2_part, l3_part = _split_two_lines(dashed_label, max_len=28)
            adv_route = {
                "line1": "Policy Feedback:" if is_logical else "Private Service Route:",
                "line2": l2_part,
                "line3": l3_part,
            }
    else:
        adv_route = None

    spoke_rows: list[list[dict[str, Any]]] = []
    row_sgs = spoke_perim_sg.get("children") or []
    for r_idx, r_sg in enumerate(row_sgs):
        row_cells: list[dict[str, Any]] = []
        r_title = r_sg.get("title", f"Row {r_idx + 1}")
        for c_idx, c in enumerate(r_sg.get("cards") or []):
            row_cells.append(
                {
                    "titleLines": _derive_spoke_cell_header(r_title, c["line1"], c["line2"], r_idx, c_idx, is_logical),
                    "card": {
                        "line1": c["line1"],
                        "line2": c["line2"],
                        "line3": c.get("line3", ""),
                        "icon": _infer_card_icon(c["line1"], c["line2"], "spoke", is_logical),
                    },
                }
            )
        spoke_rows.append(row_cells)

    return {
        "id": diagram_id,
        "cloudTitle": cloud_sg.get("title", "Enterprise Target Platform"),
        "onPremises": {
            "titleLines": _split_two_lines(onprem_sg.get("title", "External Tier"), max_len=18),
            "cards": onprem_cards,
        },
        "advertisedRoute": adv_route,
        "edgeCards": edge_cards,
        "hubProject": {
            "title": hub_proj_sg.get("title", ""),
            "vpcTitle": vpc_sg.get("title", ""),
            "regions": regions,
        },
        "spokeRows": spoke_rows,
    }


def validate_gcp_diagram_spec(
    spec: dict[str, Any],
    label: str,
    other_spec: dict[str, Any] | None = None,
    cap_group_ids: list[str] | None = None,
    target_stack: dict[str, Any] | None = None,
) -> list[str]:
    """Validates that an architecture diagram spec (parsed from Mermaid `flowchart LR`) is application-specific.

    Structural minimums are *patterns*, not fixed counts: >= 1 persona/client card, >= 1 edge card, >= 1 region
    container with >= 1 card, a dashed route/feedback connector, and a spoke grid with >= 1 row of >= 1 card.
    Uniqueness thresholds are derived from the number of cards actually drawn.
    """
    errors: list[str] = []
    if not isinstance(spec, dict):
        return [f"{label}: diagram specification must be a dictionary."]

    on_prem = spec.get("onPremises")
    if not isinstance(on_prem, dict) or (not on_prem.get("gatewayCard") and not on_prem.get("cards")):
        errors.append(f"{label}: SG_OnPrem must declare >= 1 Persona/Client card.")

    edge_cards = spec.get("edgeCards")
    if not isinstance(edge_cards, list) or len(edge_cards) < 1:
        errors.append(f"{label}: SG_Edge must declare >= 1 card (UI workspaces in §1, edge security / ingress services in §2).")

    hub = spec.get("hubProject")
    regions = hub.get("regions") if isinstance(hub, dict) else None
    if not isinstance(regions, list) or len(regions) < 1:
        errors.append(f"{label}: SG_HubProject / SG_SharedVPC must declare >= 1 region subgraph (SG_Region1, SG_Region2, …) containing component cards.")
    else:
        empty = [str(r.get("title") or f"#{i + 1}") for i, r in enumerate(regions) if not r.get("cardCount")]
        if empty:
            errors.append(f"{label}: region subgraph(s) {empty} declare no component cards.")

    adv = spec.get("advertisedRoute")
    if not isinstance(adv, dict) or not adv.get("line2"):
        errors.append(f"{label}: diagram must declare a dashed route/feedback connector ('-.->|...|').")

    spoke_rows = spec.get("spokeRows")
    if not isinstance(spoke_rows, list) or len(spoke_rows) < 1 or any(not isinstance(r, list) or len(r) < 1 for r in spoke_rows):
        errors.append(f"{label}: SG_SpokePerimeter must declare >= 1 row subgraph (e.g. SG_ProdRow, SG_NonProdRow, SG_DevRow), each with >= 1 card.")
        return errors

    # Anti-boilerplate check 1: Forbid repeating generic "Compute Engine" or "Virtual Private Cloud" across the grid
    card_sigs: list[str] = []
    for row in spoke_rows:
        for cell in row:
            c = (cell or {}).get("card") or {}
            sig = f"{str(c.get('line1', '')).strip().lower()}|{str(c.get('line2', '')).strip().lower()}"
            card_sigs.append(sig)
    n_cards = len(card_sigs)
    grid_desc = f"{len(spoke_rows)}x{max(len(r) for r in spoke_rows)}"
    if card_sigs.count("compute|engine") >= 2 or card_sigs.count("virtual|private cloud") >= 2:
        errors.append(
            f"{label}: Architecture diagram repeats generic 'Compute Engine' or 'Virtual Private Cloud' cards across the {grid_desc} grid. "
            f"Every cell in the grid MUST name a distinct, application-specific business capability service, "
            f"logical domain data store, or cloud platform service."
        )
    min_unique = max(1, -(-3 * n_cards // 4))  # ceil(75 %) of the cards drawn (7 of 9 for the classic 3x3)
    if len(set(card_sigs)) < min_unique:
        errors.append(
            f"{label}: Architecture diagram {grid_desc} grid has duplicate card labels ({len(set(card_sigs))}/{n_cards} unique; need >= {min_unique}). "
            f"Each cell must represent a distinct business capability, domain data store, or cloud platform component."
        )

    blob = str(spec).lower()
    if '"nvas"' in blob:
        errors.append(
            f"{label}: Architecture diagram contains generic reference placeholder 'NVAs'. Replace with the actual "
            f"business capability / policy guard (§1) or concrete platform runtime service (§2)."
        )

    # Anti-boilerplate check 2: Forbid spec/design trace codes (GRP-01, FRP-04, BR-01, REQ-FUNC-01, US-FUNC-01, Spec §3.3) in Architecture diagrams
    leaked_codes = re.findall(r"\b(?:grp-\d+|cap-\d+|frp-\d+|br-\d+|req-(?:func|arch|nfr|enh)-\d+|us-(?:func|tech)-\d+)\b|spec\s*§\s*\d+", blob)
    if leaked_codes:
        errors.append(
            f"{label}: Architecture diagram contains spec/design trace codes ({sorted(set(leaked_codes))[:5]}). "
            f"Keep GRP-*, FRP-*, BR-*, REQ-*, US-*, and Spec §* identifiers in specs/ and design/solution_design.md ONLY; "
            f"§1 Logical Architecture must use pure Business Capability names, and §2 Technical Architecture must use "
            f"Platform-of-Choice services (e.g., GKE, Cloud Load Balancing, Cloud Armor, AlloyDB/Cloud SQL, Cloud Logging, Cloud Monitoring)."
        )

    # Anti-boilerplate check 3: Logical vs Technical diagram differentiation
    is_logical = "logical" in label.lower() or str(spec.get("id", "")).lower().startswith("logical")
    if not is_logical:
        platform_keywords = (
            "kubernetes", "gke", "load balanc", "waf", "armor", "cdn", "postgres", "alloydb",
            "cloud sql", "sqlite", "pgbouncer", "object storage", "cloud storage", "kms",
            "secret", "opentelemetry", "otel", "logging", "monitoring", "prometheus", "gitops", "config sync",
        )
        if not any(pk in blob for pk in platform_keywords):
            errors.append(
                f"{label}: Technical Architecture diagram must depict concrete Platform-of-Choice infrastructure services "
                f"(e.g., Kubernetes / Container Runtime, Global L7 Load Balancer, WAF, Managed PostgreSQL HA, "
                f"Object Storage, KMS & Secrets Manager, OpenTelemetry Logging/Tracing/Metrics, GitOps)."
            )
        declared_db = str(((target_stack or {}).get("database") or {}).get("kind") or "").strip().lower()
        if declared_db and declared_db not in ("tbd", "sqlite") and "sqlite" in blob:
            errors.append(
                f"{label}: Future-State Infrastructure diagram mentions 'SQLite' even though specs/target_stack.json "
                f"declares database.kind={declared_db!r}. Depict only the target production database in Stage 4A."
            )

    if other_spec and isinstance(other_spec, dict):
        other_rows = other_spec.get("spokeRows") or []
        other_sigs = [
            f"{str(((cell or {}).get('card') or {}).get('line1', '')).strip().lower()}"
            for row in other_rows
            for cell in (row if isinstance(row, list) else [])
        ]
        this_l1 = [s.split("|")[0] for s in card_sigs]
        overlap = set(this_l1) & set(other_sigs)
        if len(overlap) > max(3, n_cards // 3):
            errors.append(
                f"{label}: §1 Logical Architecture and §2 Technical Architecture gcp-arch-diagram blocks share too many "
                f"identical spoke-grid card titles ({sorted(overlap)}). §1 must show Business Personas, User Experience Channels, "
                f"Domain Orchestration/Policy Core, and Business Capability Services; §2 must show Platform-of-Choice "
                f"Infrastructure (GKE, Cloud Load Balancing, Cloud Armor, AlloyDB/Cloud SQL, Cloud Storage, Cloud KMS, Cloud Logging, Cloud Monitoring)."
            )

    return errors


# Canonical shape of `resources/reference_gcp_architecture_diagram.png` (the layout every §1 / §2 diagram is
# expected to follow): persona column, 4 edge cards, hub with 2 region bands, 3×3 spoke grid.
REFERENCE_LAYOUT = {"personaCards": 3, "edgeCards": 4, "regions": 2, "spokeRows": 3, "spokeCols": 3}


def reference_layout_warnings(spec: dict[str, Any], label: str) -> list[str]:
    """Non-blocking drift report against the canonical reference layout.

    `validate_gcp_diagram_spec` only enforces pattern minimums; this helper tells the author *how* a diagram
    deviates from the reference shape (which the renderer still draws faithfully) so the Business Capability
    diagram keeps the same visual structure across projects unless a deviation is intentional.
    """
    if not isinstance(spec, dict):
        return []
    on_prem = spec.get("onPremises") if isinstance(spec.get("onPremises"), dict) else {}
    personas = len(on_prem.get("cards") or []) + (1 if on_prem.get("gatewayCard") else 0)
    edge = len(spec.get("edgeCards") or [])
    hub = spec.get("hubProject") if isinstance(spec.get("hubProject"), dict) else {}
    regions = len(hub.get("regions") or [])
    rows = [r for r in (spec.get("spokeRows") or []) if isinstance(r, list)]
    cols = max((len(r) for r in rows), default=0)
    drift: list[str] = []
    if personas != REFERENCE_LAYOUT["personaCards"]:
        drift.append(f"{personas} persona/client card(s) (reference: {REFERENCE_LAYOUT['personaCards']})")
    if edge != REFERENCE_LAYOUT["edgeCards"]:
        drift.append(f"{edge} edge card(s) (reference: {REFERENCE_LAYOUT['edgeCards']})")
    if regions != REFERENCE_LAYOUT["regions"]:
        drift.append(f"{regions} region band(s) (reference: {REFERENCE_LAYOUT['regions']})")
    if len(rows) != REFERENCE_LAYOUT["spokeRows"] or cols != REFERENCE_LAYOUT["spokeCols"] or any(len(r) != cols for r in rows):
        drift.append(f"{len(rows)}x{cols} spoke grid (reference: {REFERENCE_LAYOUT['spokeRows']}x{REFERENCE_LAYOUT['spokeCols']}, uniform rows)")
    if not drift:
        return []
    return [
        f"{label}: layout deviates from the Google Cloud reference diagram — " + "; ".join(drift)
        + ". The SVG is still rendered, but keep the reference shape (persona column → 4 edge cards → hub with 2 region bands "
        "→ 3x3 capability grid) unless the deviation is intentional, so §1 Business Capability diagrams stay comparable across projects."
    ]


_CHROME_CANDIDATES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge")


def find_chrome_binary() -> str | None:
    """Chrome/Chromium binary: dlc_common.find_chrome_binary() when available, else CHROME_BIN / PATH lookup."""
    try:
        import dlc_common as _dlc  # type: ignore  # noqa: WPS433 (optional; present when run from extract_contracts.py)
        finder = getattr(_dlc, "find_chrome_binary", None)
        if callable(finder):
            found = finder()
            if found:
                return str(found)
    except Exception:
        pass
    env_bin = os.environ.get("CHROME_BIN", "").strip()
    if env_bin and (Path(env_bin).is_file() or shutil.which(env_bin)):
        return shutil.which(env_bin) or env_bin
    for c in _CHROME_CANDIDATES:
        w = shutil.which(c)
        if w:
            return w
    return None


def _chrome_headless_flags(profile_dir: Path | None = None) -> list[str]:
    """`--no-sandbox` only when running as root or when DLC_CHROME_NO_SANDBOX=1 is set explicitly; a private
    `--user-data-dir` avoids blocking on the default profile lock when another Chrome instance is running."""
    flags = ["--headless=new", "--disable-gpu", "--hide-scrollbars"]
    if profile_dir is not None:
        flags.append(f"--user-data-dir={profile_dir}")
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    if is_root or os.environ.get("DLC_CHROME_NO_SANDBOX") == "1":
        flags.append("--no-sandbox")
    return flags


def _svg_size(svg_text: str) -> tuple[int, int]:
    m = re.search(r'<svg[^>]*\swidth="(\d+)"[^>]*\sheight="(\d+)"', svg_text)
    return (int(m.group(1)), int(m.group(2))) if m else (1320, 500)


def write_svg_and_png(spec: dict[str, Any], svg_path: Path) -> tuple[Path, Path | None]:
    """Writes the Google Cloud Reference Style SVG to `svg_path` and renders a PNG sibling if headless Chrome is available."""
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_text = render_gcp_reference_svg(spec)
    svg_path.write_text(svg_text, encoding="utf-8")
    png_path = svg_path.with_suffix(".png")
    chrome_bin = find_chrome_binary()
    if chrome_bin:
        w, h = _svg_size(svg_text)
        profile_dir = Path(tempfile.mkdtemp(prefix="dlc-chrome-profile-"))
        try:
            subprocess.run(
                [
                    chrome_bin,
                    *_chrome_headless_flags(profile_dir),
                    f"--window-size={w},{h}",
                    f"--screenshot={png_path}",
                    svg_path.resolve().as_uri(),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
            if png_path.exists() and png_path.stat().st_size > 0:
                return svg_path, png_path
        except (subprocess.TimeoutExpired, OSError):
            pass
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)
    return svg_path, None


# ===========================================================================
# Slide-8 Reference Style Business Architecture & Capability Map Renderer
# (`resources/reference_business_capability_map.png`)
# ===========================================================================
def _wrap_lines(text: str, max_chars: int = 22, max_lines: int = 3) -> list[str]:
    """Wraps a capability or value-stream label into balanced lines."""
    clean = html.unescape(re.sub(r"<[^>]+>", " ", str(text or ""))).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        return [""]
    words = clean.split(" ")
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip() if cur else w
        if len(cand) <= max_chars or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        kept = lines[: max_lines - 1]
        tail = " ".join(lines[max_lines - 1 :])
        if len(tail) > max_chars + 3:
            tail = tail[: max_chars + 1].rstrip() + "…"
        kept.append(tail)
        return kept
    return lines


def _centered_multiline_text(
    cx: float,
    cy: float,
    lines: list[str],
    font_size: float = 12.5,
    font_weight: str = "500",
    fill: str = "#202124",
    line_height: float = 15.0,
) -> str:
    n = len(lines)
    if n == 0:
        return ""
    start_y = cy - ((n - 1) * line_height) / 2.0 + (font_size * 0.35)
    out: list[str] = []
    for idx, ln in enumerate(lines):
        y = start_y + idx * line_height
        out.append(
            f'<text x="{cx:.1f}" y="{y:.1f}" text-anchor="middle" '
            f'font-size="{font_size:.1f}" font-weight="{font_weight}" fill="{fill}">{_esc(ln)}</text>'
        )
    return "\n".join(out)


def render_capability_map_svg(spec: dict[str, Any]) -> str:
    """Renders the Google Cloud Executive Business Capability Map SVG (1440x810, 16:9) modeled on Slide 8 (`v_map`).

    Visual anatomy matching `resources/reference_business_capability_map.png`:
    1. Top-left bold header `<Application Name> Capability Map` (#202124).
    2. Top horizontal Value-Stream Chevron Ribbon (`1. ...`, `2. ...`, `3. ...`, `4. ...`) in Google Blue (#4285F4)
       with #202124 1.5px borders and bold white centered text:
       - Pillar 1 is a `HOME_PLATE` polygon (flat left edge, pointed right chevron tip)
       - Pillars 2..N are interlocking `CHEVRON` polygons (notched left edge, pointed right chevron tip)
       - Each Value-Stream Chevron spans 1 or 2 capability columns underneath it.
    3. Multi-column Core Business Capability Grid below each Value-Stream Chevron (4–5 rows per column) in uniform
       #EEEEEE rectangles with #202124 1.5px borders (no Phase 1 / MVP color-coding), plus an optional bottom-row
       Cross-Cutting / Spanning Outcome Bar (`spanningOutcome`).
    4. Full-width Google Blue (#4285F4) `Foundational Capabilities` `HOME_PLATE` chevron banner.
    5. 2x6 Foundational Capabilities grid (12 cells in #EEEEEE with #202124 borders) at the bottom.
    """
    title = str(spec.get("title") or "Enterprise Application Capability Map").strip()
    if not title.lower().endswith("capability map"):
        title = f"{title} Capability Map"

    value_streams: list[dict[str, Any]] = list(spec.get("valueStreams") or [])
    foundational: list[dict[str, Any]] = list(spec.get("foundationalCapabilities") or [])
    spanning_outcome: dict[str, Any] | None = spec.get("spanningOutcome")

    # Flatten columns across all value streams
    flat_columns: list[list[dict[str, Any]]] = []
    pillar_spans: list[tuple[dict[str, Any], int, int]] = []
    for vs in value_streams:
        cols = vs.get("columns") or []
        if not cols:
            cards = vs.get("cards") or []
            if len(cards) > 5:
                mid = (len(cards) + 1) // 2
                cols = [cards[:mid], cards[mid:]]
            else:
                cols = [cards]
        start_c = len(flat_columns)
        for col in cols:
            flat_columns.append(list(col))
        end_c = len(flat_columns) - 1
        pillar_spans.append((vs, start_c, max(start_c, end_c)))

    total_cols = max(len(flat_columns), 4)
    left_x = 56.0
    right_x = 1384.0
    usable_w = right_x - left_x  # 1328px
    col_gap = 12.0
    col_w = (usable_w - (total_cols - 1) * col_gap) / total_cols

    def _col_x(c_idx: int) -> float:
        return left_x + c_idx * (col_w + col_gap)

    svg: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 810" width="1440" height="810" '
        'font-family="\'Google Sans\', \'Roboto\', \'Inter\', -apple-system, BlinkMacSystemFont, \'Segoe UI\', Arial, sans-serif">',
        '<rect x="0" y="0" width="1440" height="810" fill="#FFFFFF"/>',
        f'<text x="{left_x:.1f}" y="62" font-size="27" font-weight="700" fill="#202124">{_esc(title)}</text>',
    ]

    # 1. Top Value-Stream Chevron Ribbon (y=94, h=56)
    chev_y = 94.0
    chev_h = 56.0
    tip_dx = 16.0
    num_pillars = len(pillar_spans)
    for p_idx, (vs, c_start, c_end) in enumerate(pillar_spans):
        x0 = _col_x(c_start) - (3.0 if p_idx > 0 else 0.0)
        x1 = _col_x(c_end) + col_w + (3.0 if p_idx < num_pillars - 1 else 0.0)
        ym = chev_y + chev_h / 2.0
        y1 = chev_y + chev_h
        if p_idx == 0:
            # HOME_PLATE polygon (flat left edge, chevron tip on right)
            pts = (
                f"{x0:.1f},{chev_y:.1f} "
                f"{x1 - tip_dx:.1f},{chev_y:.1f} "
                f"{x1:.1f},{ym:.1f} "
                f"{x1 - tip_dx:.1f},{y1:.1f} "
                f"{x0:.1f},{y1:.1f}"
            )
            text_cx = (x0 + (x1 - tip_dx)) / 2.0
        else:
            # Interlocking CHEVRON polygon (notched left edge, chevron tip on right)
            pts = (
                f"{x0:.1f},{chev_y:.1f} "
                f"{x1 - tip_dx:.1f},{chev_y:.1f} "
                f"{x1:.1f},{ym:.1f} "
                f"{x1 - tip_dx:.1f},{y1:.1f} "
                f"{x0:.1f},{y1:.1f} "
                f"{x0 + tip_dx:.1f},{ym:.1f}"
            )
            text_cx = (x0 + tip_dx + (x1 - tip_dx)) / 2.0

        svg.append(
            f'<polygon points="{pts}" fill="#4285F4" stroke="#202124" stroke-width="1.5" stroke-linejoin="round"/>'
        )
        span_cols = c_end - c_start + 1
        max_chars = 24 if span_cols == 1 else max(28, int(((x1 - x0) - 28) / 7.0))
        vs_lines = _wrap_lines(vs.get("title", f"{p_idx + 1}. Value Stream"), max_chars=max_chars, max_lines=3 if span_cols == 1 else 2)
        fs = 11.8 if (span_cols == 1 and len(vs_lines) >= 3) else (12.5 if (span_cols == 1 and len(vs_lines) > 1) else 13.8)
        lh = 13.5 if len(vs_lines) >= 3 else 16.0
        svg.append(
            _centered_multiline_text(
                text_cx,
                ym,
                vs_lines,
                font_size=fs,
                font_weight="700",
                fill="#FFFFFF",
                line_height=lh,
            )
        )

    # 2. Core Business Capability Grid (up to 5 rows: y=166, 227, 288, 349, 410)
    grid_top_y = 166.0
    card_h = 52.0
    row_gap = 9.0

    def _row_y(r_idx: int) -> float:
        return grid_top_y + r_idx * (card_h + row_gap)

    span_start_col = None
    span_row_idx = 4
    if isinstance(spanning_outcome, dict) and spanning_outcome.get("title"):
        default_start = 2 if total_cols >= 5 else (1 if total_cols >= 3 else 0)
        span_start_col = int(spanning_outcome.get("startCol", default_start))
        span_start_col = max(0, min(span_start_col, total_cols - 1))
        span_row_idx = int(spanning_outcome.get("row", 4))

    card_max_chars = max(16, int((col_w - 16) / 6.6))
    for c_idx, col_cards in enumerate(flat_columns):
        cx = _col_x(c_idx)
        max_rows_for_col = span_row_idx if (span_start_col is not None and c_idx >= span_start_col) else 5
        for r_idx, card in enumerate(col_cards[:max_rows_for_col]):
            cy = _row_y(r_idx)
            svg.append(
                f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{col_w:.1f}" height="{card_h:.1f}" '
                f'fill="#EEEEEE" stroke="#202124" stroke-width="1.5"/>'
            )
            c_lines = _wrap_lines(card.get("title", ""), max_chars=card_max_chars, max_lines=3)
            fs = 11.5 if len(c_lines) >= 3 else 12.3
            lh = 13.5 if len(c_lines) >= 3 else 14.8
            svg.append(
                _centered_multiline_text(
                    cx + col_w / 2.0,
                    cy + card_h / 2.0,
                    c_lines,
                    font_size=fs,
                    font_weight="500",
                    fill="#202124",
                    line_height=lh,
                )
            )

    # Render Cross-Cutting / Spanning Outcome Bar on Row 5 (matching Slide 8 `Program, Referral & Outcome Management`)
    if span_start_col is not None and spanning_outcome:
        sx = _col_x(span_start_col)
        sw = (_col_x(total_cols - 1) + col_w) - sx
        sy = _row_y(span_row_idx)
        svg.append(
            f'<rect x="{sx:.1f}" y="{sy:.1f}" width="{sw:.1f}" height="{card_h:.1f}" '
            f'fill="#EEEEEE" stroke="#202124" stroke-width="1.5"/>'
        )
        span_lines = _wrap_lines(spanning_outcome.get("title", ""), max_chars=max(32, int((sw - 24) / 7.0)), max_lines=2)
        svg.append(
            _centered_multiline_text(
                sx + sw / 2.0,
                sy + card_h / 2.0,
                span_lines,
                font_size=13.0,
                font_weight="500",
                fill="#202124",
                line_height=15.5,
            )
        )

    # 3. Full-Width `Foundational Capabilities` Banner (HOME_PLATE chevron at y=482, h=44)
    fb_y = 482.0
    fb_h = 44.0
    fb_ym = fb_y + fb_h / 2.0
    fb_y1 = fb_y + fb_h
    fb_pts = (
        f"{left_x:.1f},{fb_y:.1f} "
        f"{right_x - tip_dx:.1f},{fb_y:.1f} "
        f"{right_x:.1f},{fb_ym:.1f} "
        f"{right_x - tip_dx:.1f},{fb_y1:.1f} "
        f"{left_x:.1f},{fb_y1:.1f}"
    )
    svg.append(
        f'<polygon points="{fb_pts}" fill="#4285F4" stroke="#202124" stroke-width="1.5" stroke-linejoin="round"/>'
    )
    svg.append(
        _centered_multiline_text(
            (left_x + right_x - tip_dx) / 2.0,
            fb_ym,
            [str(spec.get("foundationalTitle") or "Foundational Capabilities")],
            font_size=15.0,
            font_weight="700",
            fill="#FFFFFF",
        )
    )

    # 4. Foundational Capabilities 2x6 Grid (y=538 and y=600, h=50)
    f_cols = 6
    f_gap = 14.0
    f_w = (usable_w - (f_cols - 1) * f_gap) / f_cols
    f_h = 50.0
    f_row_ys = [538.0, 600.0]
    f_max_chars = max(18, int((f_w - 16) / 6.6))
    for idx, f_card in enumerate(foundational[:12]):
        r_idx = idx // f_cols
        c_idx = idx % f_cols
        fx = left_x + c_idx * (f_w + f_gap)
        fy = f_row_ys[r_idx]
        svg.append(
            f'<rect x="{fx:.1f}" y="{fy:.1f}" width="{f_w:.1f}" height="{f_h:.1f}" '
            f'fill="#EEEEEE" stroke="#202124" stroke-width="1.5"/>'
        )
        flines = _wrap_lines(f_card.get("title", ""), max_chars=f_max_chars, max_lines=2)
        svg.append(
            _centered_multiline_text(
                fx + f_w / 2.0,
                fy + f_h / 2.0,
                flines,
                font_size=12.2,
                font_weight="500",
                fill="#202124",
                line_height=14.5,
            )
        )

    svg.append("</svg>")
    return "\n".join(svg) + "\n"


def parse_capability_map_mermaid(mermaid_text: str, app_title: str = "") -> dict[str, Any]:
    """Parses the `§1 Business Architecture & Capability Map` Mermaid `flowchart TB` block into a capability map spec."""
    root_children: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    spanning_outcome: dict[str, Any] | None = None
    map_title = app_title.strip()

    for raw_line in mermaid_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("%%"):
            m_title = re.match(r"^%%\s*title\s*:\s*(.+)$", line, flags=re.IGNORECASE)
            if m_title:
                map_title = m_title.group(1).strip()
            continue
        sg_m = re.match(r"^subgraph\s+([A-Za-z0-9_]+)(?:\s*\[\s*\"?(.*?)\"?\s*\])?\s*$", line)
        if sg_m:
            sg_id = sg_m.group(1)
            sg_title = html.unescape(sg_m.group(2) or sg_id).strip()
            sg_title = re.sub(r"</?b>", "", sg_title).strip()
            sg_node: dict[str, Any] = {"id": sg_id, "title": sg_title, "cards": [], "children": []}
            if stack:
                stack[-1]["children"].append(sg_node)
            else:
                root_children.append(sg_node)
            stack.append(sg_node)
            continue
        if line == "end":
            if stack:
                stack.pop()
            continue
        if any(tok in line for tok in ("-->", "==>", "-.->", "classDef ", "style ", "direction ")):
            continue
        card_m = re.match(r"^([A-Za-z0-9_]+)\s*\[\s*\"(.*?)\"\s*\](?::::([A-Za-z0-9_]+))?", line)
        if card_m and stack:
            node_id = card_m.group(1)
            raw_label = html.unescape(card_m.group(2))
            cls_name = (card_m.group(3) or "").strip()
            clean_label = " / ".join(
                re.sub(r"</?b>", "", p).strip()
                for p in re.split(r"<br\s*/?>", raw_label, flags=re.IGNORECASE)
                if p.strip()
            )
            is_mvp = cls_name.lower() in ("capmvp", "focal", "gcpgreen")
            is_span = cls_name.lower() in ("capspan", "spanning") or "span" in stack[-1]["id"].lower()
            card_obj = {"id": node_id, "title": clean_label, "mvp": is_mvp}
            if is_span:
                spanning_outcome = {"title": clean_label, "mvp": is_mvp, "startCol": 2}
            else:
                stack[-1]["cards"].append(card_obj)

    # Unwrap optional outer wrapper subgraph if a single outer container holds all pillars + foundational
    top_sgs = root_children
    if len(top_sgs) == 1 and len(top_sgs[0].get("children") or []) >= 3:
        if not map_title:
            map_title = top_sgs[0].get("title", "")
        top_sgs = top_sgs[0]["children"]

    value_streams: list[dict[str, Any]] = []
    foundational: list[dict[str, Any]] = []
    foundational_title = "Foundational Capabilities"

    for sg in top_sgs:
        sg_id_low = sg["id"].lower()
        sg_title_low = sg["title"].lower()
        if "found" in sg_id_low or "foundational" in sg_title_low:
            foundational_title = sg["title"] or "Foundational Capabilities"
            foundational.extend(sg.get("cards") or [])
            for child in sg.get("children") or []:
                foundational.extend(child.get("cards") or [])
        elif "span" in sg_id_low or "cross-cutting" in sg_title_low or "outcome" in sg_id_low:
            if sg.get("cards") and not spanning_outcome:
                c0 = sg["cards"][0]
                spanning_outcome = {"title": c0["title"], "mvp": c0.get("mvp", False), "startCol": 2}
        else:
            cols: list[list[dict[str, Any]]] = []
            if sg.get("children"):
                for child in sg["children"]:
                    if child.get("cards"):
                        cols.append(child["cards"])
            if sg.get("cards"):
                cards = sg["cards"]
                if len(cards) > 5:
                    mid = (len(cards) + 1) // 2
                    cols.extend([cards[:mid], cards[mid:]])
                else:
                    cols.append(cards)
            if cols:
                value_streams.append({"id": sg["id"], "title": sg["title"], "columns": cols})

    return {
        "title": map_title or "Enterprise Application Capability Map",
        "valueStreams": value_streams,
        "spanningOutcome": spanning_outcome,
        "foundationalTitle": foundational_title,
        "foundationalCapabilities": foundational,
    }


def validate_capability_map_spec(
    spec: dict[str, Any],
    label: str = "§1 Business Architecture & Capability Map",
) -> list[str]:
    """Validates that the `§1 Business Architecture & Capability Map` diagram conforms to the Slide 8 standard."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        return [f"{label}: capability map specification must be a dictionary."]

    value_streams = spec.get("valueStreams") or []
    if len(value_streams) < 3:
        errors.append(
            f"{label}: Business Capability Map must declare >= 3 top-level Value-Stream / Lifecycle Pillars "
            f"(e.g., '1. ...', '2. ...', '3. ...', '4. ...' subgraphs; found {len(value_streams)})."
        )

    core_cards: list[str] = []
    for vs in value_streams:
        for col in vs.get("columns") or []:
            for c in col:
                if c.get("title"):
                    core_cards.append(str(c["title"]).strip())
    if isinstance(spec.get("spanningOutcome"), dict) and spec["spanningOutcome"].get("title"):
        core_cards.append(str(spec["spanningOutcome"]["title"]).strip())

    if len(core_cards) < 12:
        errors.append(
            f"{label}: Business Capability Map must declare >= 12 Core Business Capabilities across the Value-Stream columns "
            f"(found {len(core_cards)})."
        )

    foundational = spec.get("foundationalCapabilities") or []
    if len(foundational) < 6:
        errors.append(
            f"{label}: Business Capability Map must include a 'Foundational Capabilities' subgraph with >= 6 foundational "
            f"capabilities (12 recommended in a 2x6 grid matching resources/reference_business_capability_map.png; found {len(foundational)})."
        )

    blob = " ".join(
        [str(spec.get("title", ""))]
        + [str(vs.get("title", "")) for vs in value_streams]
        + core_cards
        + [str(f.get("title", "")) for f in foundational]
    )
    leaked_codes = re.findall(
        r"\b(?:GRP-\d+|CAP-\d+|FRP-\d+|BR-\d+|REQ-(?:FUNC|ARCH|NFR|ENH)-\d+|US-(?:FUNC|TECH)-\d+)\b|Spec\s*§\s*\d+",
        blob,
        re.IGNORECASE,
    )
    if leaked_codes:
        errors.append(
            f"{label}: Business Capability Map contains spec/design trace codes ({sorted(set(leaked_codes))[:5]}). "
            f"Use pure human-readable Business Capability and Value-Stream names only (never GRP-01, CAP-01, FRP-04, BR-01, REQ-*, or US-*)."
        )

    return errors


def _save_svg_and_png(svg_text: str, svg_path: Path, width: int = 1440, height: int = 840) -> tuple[Path, Path | None]:
    """Writes `svg_text` to `svg_path` and renders a PNG sibling at `width x height` if headless Chrome is available."""
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg_text, encoding="utf-8")
    png_path = svg_path.with_suffix(".png")
    chrome_bin = find_chrome_binary()
    if chrome_bin:
        w, h = _svg_size(svg_text) if (width <= 0 or height <= 0) else (width, height)
        profile_dir = Path(tempfile.mkdtemp(prefix="dlc-chrome-profile-"))
        try:
            subprocess.run(
                [
                    chrome_bin,
                    *_chrome_headless_flags(profile_dir),
                    f"--window-size={w},{h}",
                    f"--screenshot={png_path}",
                    svg_path.resolve().as_uri(),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
            if png_path.exists() and png_path.stat().st_size > 0:
                return svg_path, png_path
        except (subprocess.TimeoutExpired, OSError):
            pass
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)
    return svg_path, None


def write_capability_map_svg_and_png(spec: dict[str, Any], svg_path: Path) -> tuple[Path, Path | None]:
    """Writes the Slide-8-style Business Capability Map SVG (`1440x810`) to `svg_path` and renders a PNG sibling."""
    return _save_svg_and_png(render_capability_map_svg(spec), svg_path, width=1440, height=810)


# ===========================================================================
# Multi-Perspective Enterprise Architecture Renderers
# 1. High-Level Solution Architecture (`reference_high_level_solution_architecture.png` + System of AI)
# 2. Application Architecture (Multi-Tier C4 & AI Agent Component Topology)
# 3. Data Architecture (5-Stage Data Lifecycle, 3NF System of Record, MDM & AI Grounding)
# 4. Security & AI Trust Architecture (5-Layer Defense-in-Depth + Continuous Compliance)
# ===========================================================================
def parse_layered_perspective_mermaid(mermaid_text: str, app_title: str = "") -> dict[str, Any]:
    """Parses a multi-subgraph Mermaid flowchart into a structured dict of subgraphs and cards for multi-perspective rendering."""
    root_children: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    all_sgs: dict[str, dict[str, Any]] = {}
    diagram_title = app_title.strip()
    diagram_subtitle = ""
    platform_title = ""

    for raw_line in mermaid_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("%%"):
            m_title = re.match(r"^%%\s*title\s*:\s*(.+)$", line, flags=re.IGNORECASE)
            if m_title:
                diagram_title = m_title.group(1).strip()
            m_sub = re.match(r"^%%\s*subtitle\s*:\s*(.+)$", line, flags=re.IGNORECASE)
            if m_sub:
                diagram_subtitle = m_sub.group(1).strip()
            m_plat = re.match(r"^%%\s*platform_title\s*:\s*(.+)$", line, flags=re.IGNORECASE)
            if m_plat:
                platform_title = m_plat.group(1).strip()
            continue
        sg_m = re.match(r"^subgraph\s+([A-Za-z0-9_]+)(?:\s*\[\s*\"?(.*?)\"?\s*\])?\s*$", line)
        if sg_m:
            sg_id = sg_m.group(1)
            sg_title = html.unescape(sg_m.group(2) or sg_id).strip()
            sg_title = re.sub(r"</?b>", "", sg_title).strip()
            sg_node: dict[str, Any] = {"id": sg_id, "title": sg_title, "cards": [], "children": []}
            if stack:
                stack[-1]["children"].append(sg_node)
            else:
                root_children.append(sg_node)
            stack.append(sg_node)
            all_sgs[sg_id.lower()] = sg_node
            continue
        if line == "end":
            if stack:
                stack.pop()
            continue
        if any(tok in line for tok in ("-->", "==>", "-.->", "classDef ", "style ", "direction ")):
            continue
        card_m = re.match(r"^([A-Za-z0-9_]+)\s*\[\s*\"(.*?)\"\s*\]", line)
        if card_m and stack:
            raw_label = html.unescape(card_m.group(2))
            parts = [re.sub(r"</?b>", "", p).strip() for p in re.split(r"<br\s*/?>", raw_label, flags=re.IGNORECASE) if p.strip()]
            l1 = parts[0] if parts else card_m.group(1)
            l2 = parts[1] if len(parts) > 1 else ""
            l3 = parts[2] if len(parts) > 2 else ""
            full_label = " — ".join(parts) if len(parts) > 1 else l1
            stack[-1]["cards"].append(
                {"id": card_m.group(1), "line1": l1, "line2": l2, "line3": l3, "title": full_label}
            )

    return {
        "title": diagram_title or "Enterprise Architecture View",
        "subtitle": diagram_subtitle,
        "platform_title": platform_title,
        "rootSubgraphs": root_children,
        "subgraphsById": all_sgs,
    }


def validate_perspective_spec(spec: dict[str, Any], label: str, min_cards: int = 8) -> list[str]:
    """Validates that a perspective diagram has sufficient domain cards and zero leaked spec/design trace codes."""
    errors: list[str] = []
    all_sgs = spec.get("subgraphsById") or {}
    all_cards: list[str] = []
    for sg in all_sgs.values():
        for c in sg.get("cards") or []:
            all_cards.append(f"{c.get('line1', '')} {c.get('line2', '')}".strip())
    if len(all_cards) < min_cards:
        errors.append(f"{label}: diagram must declare >= {min_cards} architecture component cards across its subgraphs (found {len(all_cards)}).")
    blob = " ".join([str(spec.get("title", ""))] + [sg.get("title", "") for sg in all_sgs.values()] + all_cards)
    leaked = re.findall(
        r"\b(?:GRP-\d+|CAP-\d+|FRP-\d+|BR-\d+|REQ-(?:FUNC|ARCH|NFR|ENH)-\d+|US-(?:FUNC|TECH)-\d+)\b|Spec\s*§\s*\d+",
        blob,
        re.IGNORECASE,
    )
    if leaked:
        errors.append(
            f"{label}: diagram contains spec/design trace codes ({sorted(set(leaked))[:5]}). "
            f"Keep GRP-*, CAP-*, FRP-*, BR-*, REQ-*, and US-* identifiers in specs/ and design/solution_design.md ONLY."
        )
    return errors


def _find_sg_in_parsed(parsed: dict[str, Any], *prefixes: str) -> dict[str, Any] | None:
    sgs = parsed.get("subgraphsById") or {}
    # Pass 1: exact key match
    for pref in prefixes:
        p_low = pref.lower()
        if p_low in sgs:
            return sgs[p_low]
    # Pass 2: prefix or substring match on subgraphs that contain cards
    for pref in prefixes:
        p_low = pref.lower()
        for k, v in sgs.items():
            if (k.startswith(p_low) or p_low in k) and v.get("cards"):
                return v
    # Pass 3: any prefix or substring match
    for pref in prefixes:
        p_low = pref.lower()
        for k, v in sgs.items():
            if k.startswith(p_low) or p_low in k:
                return v
    return None


def _draw_boxed_card(
    x: float,
    y: float,
    w: float,
    h: float,
    line1: str,
    line2: str = "",
    fill: str = "#FFFFFF",
    stroke: str = "#2C5E8A",
    stroke_w: float = 1.6,
    rx: float = 4.0,
    title_color: str = "#202124",
    sub_color: str = "#5F6368",
    badge_color: str | None = None,
) -> str:
    """Renders a clean enterprise card with optional top accent bar and wrapped 1- or 2-line label."""
    parts: list[str] = [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w:.1f}"/>'
    ]
    if badge_color:
        parts.append(
            f'<rect x="{x + 1.0:.1f}" y="{y + 1.0:.1f}" width="{w - 2.0:.1f}" height="5.0" rx="2.5" fill="{badge_color}"/>'
        )
    max_c = max(14, int((w - 18) / 6.7))
    if line2:
        l1_wrapped = _wrap_lines(line1, max_chars=max_c, max_lines=2)
        l2_wrapped = _wrap_lines(line2, max_chars=max_c + 3, max_lines=2)
        if len(l1_wrapped) == 1:
            parts.append(
                f'<text x="{x + w / 2.0:.1f}" y="{y + h / 2.0 - 5.0:.1f}" text-anchor="middle" '
                f'font-size="12.2" font-weight="700" fill="{title_color}">{_esc(l1_wrapped[0])}</text>'
            )
            parts.append(
                f'<text x="{x + w / 2.0:.1f}" y="{y + h / 2.0 + 12.0:.1f}" text-anchor="middle" '
                f'font-size="10.6" font-weight="500" fill="{sub_color}">{_esc(l2_wrapped[0])}</text>'
            )
        else:
            parts.append(
                f'<text x="{x + w / 2.0:.1f}" y="{y + h / 2.0 - 11.0:.1f}" text-anchor="middle" '
                f'font-size="11.5" font-weight="700" fill="{title_color}">{_esc(l1_wrapped[0])}</text>'
            )
            parts.append(
                f'<text x="{x + w / 2.0:.1f}" y="{y + h / 2.0 + 2.0:.1f}" text-anchor="middle" '
                f'font-size="11.5" font-weight="700" fill="{title_color}">{_esc(l1_wrapped[1])}</text>'
            )
            parts.append(
                f'<text x="{x + w / 2.0:.1f}" y="{y + h / 2.0 + 16.5:.1f}" text-anchor="middle" '
                f'font-size="10.2" font-weight="500" fill="{sub_color}">{_esc(l2_wrapped[0])}</text>'
            )
    else:
        lines = _wrap_lines(line1, max_chars=max_c, max_lines=2)
        parts.append(
            _centered_multiline_text(
                x + w / 2.0,
                y + h / 2.0,
                lines,
                font_size=12.5,
                font_weight="600",
                fill=title_color,
                line_height=15.0,
            )
        )
    return "\n".join(parts)


def render_high_level_solution_svg(parsed: dict[str, Any]) -> str:
    """Renders the Executive High-Level Future State Solution Architecture (`1440x860`).

    Modeled directly on `resources/reference_high_level_solution_architecture.png` enhanced with the
    AI-Era System of Intelligence & AI (Agentic Layer) and enterprise system-of-intelligence multi-layer structure:
    - Top Row: Business Personas & Actors with blue silhouette user avatars
    - Band 1: Engagement Layer (System of Engagement — Portals, Consoles, BI/Analytics, AI Copilot UX)
    - Band 2: System of Intelligence & AI (Thick Cyan `#00A1E0` rounded container with:
      - Top full-width `AI & Agentic Orchestration Layer`
      - Middle row of 4 Core Domain Intelligence capabilities
      - Bottom full-width `Data Ingestion, Harmonization & Event Transformation Layer`
      - Right-hand vertical stack of 4 Governance & Trust capabilities (`Built-in Data & AI Security`,
        `Unified Data Governance`, `API & Service Exchange`, `Compliance & Anomaly Detection`)
      - Bottom platform emblem & title)
    - Band 3: Transactional Systems / Systems of Record
    """
    title = str(parsed.get("title") or "Future State Architecture").strip()
    personas_sg = _find_sg_in_parsed(parsed, "sg_personas", "personas", "actors") or {"cards": []}
    engage_sg = _find_sg_in_parsed(parsed, "sg_engagement", "engagement") or {"cards": []}
    ai_sg = _find_sg_in_parsed(parsed, "sg_ailayer", "sg_ai", "agentic") or {"cards": []}
    intel_sg = _find_sg_in_parsed(parsed, "sg_corecaps", "sg_coreintelligence", "sg_domainintel", "corecaps") or {"cards": []}
    ingest_sg = _find_sg_in_parsed(parsed, "sg_datalayer", "sg_ingestion", "sg_dataingestion", "datalayer") or {"cards": []}
    gov_sg = _find_sg_in_parsed(parsed, "sg_governance", "sg_trust") or {"cards": []}
    tx_sg = _find_sg_in_parsed(parsed, "sg_transactional", "sg_record", "transactional") or {"cards": []}
    platform_sg = _find_sg_in_parsed(parsed, "sg_intelligence", "sg_systemofintelligence") or {
        "title": "Unified Intelligence, Agentic AI & Domain Data Platform"
    }

    personas = (personas_sg.get("cards") or [])[:5]
    if not personas:
        personas = [
            {"line1": "Operational Staff", "line2": "Triage & Review"},
            {"line1": "Domain Analysts", "line2": "AI & Insights"},
            {"line1": "Executives", "line2": "Oversight & KPIs"},
            {"line1": "Customers / Users", "line2": "Self-Service"},
        ]

    engage_cards = (engage_sg.get("cards") or [])[:6]
    ai_bar_card = (ai_sg.get("cards") or [{"line1": "AI & Agentic Orchestration Layer", "line2": "Domain Copilots · Autonomous Workflow Agents · RAG Grounding · Prompt Guardrails"}])[0]
    intel_cards = (intel_sg.get("cards") or [])[:4]
    ingest_bar_card = (ingest_sg.get("cards") or [{"line1": "Data Ingestion, Harmonization & Event Transformation Layer", "line2": "OpenAPI REST · Event Streaming · Validation & Normalization"}])[0]
    gov_cards = (gov_sg.get("cards") or [])[:4]
    tx_cards = (tx_sg.get("cards") or [])[:6]

    svg: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 860" width="1440" height="860" '
        'font-family="\'Google Sans\', \'Roboto\', \'Inter\', -apple-system, BlinkMacSystemFont, \'Segoe UI\', Arial, sans-serif">',
        "<defs>",
        '  <marker id="hlArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#1F5A88"/>',
        "  </marker>",
        "</defs>",
        '<rect x="0" y="0" width="1440" height="860" fill="#FFFFFF"/>',
        f'<text x="58" y="64" font-size="31" font-weight="700" fill="#202124">{_esc(title)}</text>',
    ]

    # 1. Top Row: Personas / Actors (centered above Engagement Layer)
    n_p = len(personas)
    p_span_w = min(760.0, n_p * 175.0)
    p_start_x = 800.0 - p_span_w / 2.0
    p_step = p_span_w / max(n_p, 1)
    for idx, p in enumerate(personas):
        pcx = p_start_x + (idx + 0.5) * p_step
        # Blue silhouette user avatar (matching reference image)
        svg.append(f'<circle cx="{pcx:.1f}" cy="103" r="14.5" fill="#6BAED6"/>')
        svg.append(
            f'<path d="M {pcx - 24:.1f} 145 C {pcx - 24:.1f} 124, {pcx + 24:.1f} 124, {pcx + 24:.1f} 145 Z" fill="#6BAED6"/>'
        )
        svg.append(
            f'<text x="{pcx:.1f}" y="164" text-anchor="middle" font-size="12.5" font-weight="600" fill="#3C4043">{_esc(p.get("line1", ""))}</text>'
        )
        if p.get("line2"):
            svg.append(
                f'<text x="{pcx:.1f}" y="179" text-anchor="middle" font-size="10.8" font-weight="400" fill="#5F6368">{_esc(p.get("line2", ""))}</text>'
            )

    # 2. Band 1: Engagement Layer (y=198, h=104)
    svg.append('<text x="108" y="242" text-anchor="middle" font-size="15.5" font-weight="700" fill="#4A4A4A">Engagement</text>')
    svg.append('<text x="108" y="262" text-anchor="middle" font-size="15.5" font-weight="700" fill="#4A4A4A">Layer</text>')
    svg.append('<text x="108" y="280" text-anchor="middle" font-size="11.2" font-weight="500" fill="#5F6368">(System of Engagement)</text>')

    eng_x, eng_y, eng_w, eng_h = 280.0, 198.0, 1020.0, 104.0
    svg.append(
        f'<rect x="{eng_x:.1f}" y="{eng_y:.1f}" width="{eng_w:.1f}" height="{eng_h:.1f}" rx="18" '
        f'fill="#FFFFFF" stroke="#1F5A88" stroke-width="2.0"/>'
    )
    n_eng = max(len(engage_cards), 1)
    eng_pad = 22.0
    eng_gap = 16.0
    ec_w = (eng_w - 2 * eng_pad - (n_eng - 1) * eng_gap) / n_eng
    for idx, ec in enumerate(engage_cards):
        ex = eng_x + eng_pad + idx * (ec_w + eng_gap)
        svg.append(
            _draw_boxed_card(
                ex,
                eng_y + 18.0,
                ec_w,
                68.0,
                ec.get("line1", ""),
                ec.get("line2", ""),
                fill="#F8FAFC",
                stroke="#2C5E8A",
                badge_color="#1A73E8",
            )
        )

    # Upward arrow from System of Intelligence & AI to Engagement Layer
    svg.append('<line x1="790" y1="342" x2="790" y2="306" stroke="#1F5A88" stroke-width="2.4" marker-end="url(#hlArrow)"/>')

    # 3. Band 2: System of Intelligence & AI (y=342, h=338)
    svg.append('<text x="108" y="488" text-anchor="middle" font-size="15.5" font-weight="700" fill="#4A4A4A">System of</text>')
    svg.append('<text x="108" y="508" text-anchor="middle" font-size="15.5" font-weight="700" fill="#4A4A4A">Intelligence &amp; AI</text>')
    svg.append('<text x="108" y="527" text-anchor="middle" font-size="11.2" font-weight="500" fill="#0077B5">(Agentic &amp; Domain Core)</text>')

    soi_x, soi_y, soi_w, soi_h = 216.0, 342.0, 1164.0, 338.0
    svg.append(
        f'<rect x="{soi_x:.1f}" y="{soi_y:.1f}" width="{soi_w:.1f}" height="{soi_h:.1f}" rx="34" '
        f'fill="#FFFFFF" stroke="#19A5E6" stroke-width="4.0"/>'
    )

    # Left/Center Stack inside System of Intelligence & AI (x=264..1072, w=808)
    main_x = 264.0
    main_w = 808.0

    # 3a. Top Full-Width Bar: AI & Agentic Orchestration Layer
    ai_title = ai_bar_card.get("line1", "AI & Agentic Orchestration Layer")
    ai_sub = ai_bar_card.get("line2", "")
    svg.append(
        _draw_boxed_card(
            main_x,
            372.0,
            main_w,
            58.0,
            ai_title,
            ai_sub,
            fill="#F0F7FF",
            stroke="#1F5A88",
            stroke_w=1.8,
            title_color="#0D3B66",
            sub_color="#3C4043",
        )
    )

    # 3b. Middle Row of 4 Domain Intelligence Cards (y=452, h=66)
    n_ic = max(len(intel_cards), 1)
    ic_gap = 14.0
    ic_w = (main_w - (n_ic - 1) * ic_gap) / n_ic
    for idx, ic in enumerate(intel_cards):
        ix = main_x + idx * (ic_w + ic_gap)
        svg.append(
            _draw_boxed_card(
                ix,
                452.0,
                ic_w,
                66.0,
                ic.get("line1", ""),
                ic.get("line2", ""),
                fill="#FFFFFF",
                stroke="#2C5E8A",
            )
        )

    # 3c. Bottom Full-Width Bar: Data Ingestion, Harmonization & Transformation Layer (y=540, h=56)
    ing_title = ingest_bar_card.get("line1", "Data Ingestion, Harmonization & Transformation Layer")
    ing_sub = ingest_bar_card.get("line2", "")
    svg.append(
        _draw_boxed_card(
            main_x,
            540.0,
            main_w,
            56.0,
            ing_title,
            ing_sub,
            fill="#F8FAFC",
            stroke="#2C5E8A",
            stroke_w=1.6,
        )
    )

    # 3d. Right-Hand Vertical Governance & Trust Stack (x=1096..1344, w=248, 4 stacked boxes)
    gov_x = 1096.0
    gov_w = 248.0
    gov_h = 50.0
    gov_gap = 10.5
    for idx, gc in enumerate(gov_cards[:4]):
        gy = 372.0 + idx * (gov_h + gov_gap)
        svg.append(
            _draw_boxed_card(
                gov_x,
                gy,
                gov_w,
                gov_h,
                gc.get("line1", ""),
                gc.get("line2", ""),
                fill="#F8FAFC",
                stroke="#2C5E8A",
                badge_color="#00A1E0",
            )
        )

    # 3e. Bottom Platform Emblem & Title inside Cyan Container (y=646)
    raw_plat_title = str(parsed.get("platform_title") or platform_sg.get("title") or "").strip()
    if not raw_plat_title or raw_plat_title.lower() in ("system of intelligence & ai", "system of intelligence"):
        raw_plat_title = "Unified Intelligence, Agentic AI & Domain Data Platform"
    plat_title = raw_plat_title
    emblem_cx = max(360.0, 668.0 - len(plat_title) * 4.4)
    emblem_cy = 642.0
    svg.append(f'<circle cx="{emblem_cx:.1f}" cy="{emblem_cy:.1f}" r="13" fill="#E1F5FE" stroke="#00A1E0" stroke-width="2"/>')
    svg.append(f'<path d="M {emblem_cx - 7:.1f} {emblem_cy:.1f} L {emblem_cx + 7:.1f} {emblem_cy:.1f} M {emblem_cx:.1f} {emblem_cy - 7:.1f} L {emblem_cx:.1f} {emblem_cy + 7:.1f} M {emblem_cx - 5:.1f} {emblem_cy - 5:.1f} L {emblem_cx + 5:.1f} {emblem_cy + 5:.1f} M {emblem_cx - 5:.1f} {emblem_cy + 5:.1f} L {emblem_cx + 5:.1f} {emblem_cy - 5:.1f}" stroke="#00A1E0" stroke-width="1.8"/>')
    svg.append(
        f'<text x="{emblem_cx + 22:.1f}" y="{emblem_cy + 6:.1f}" font-size="16.5" font-weight="700" fill="#4A4A4A">{_esc(plat_title)}</text>'
    )

    # Upward arrow from Transactional Systems to System of Intelligence & AI
    svg.append('<line x1="790" y1="718" x2="790" y2="682" stroke="#1F5A88" stroke-width="2.4" marker-end="url(#hlArrow)"/>')

    # 4. Band 3: Transactional Systems / Systems of Record (y=718, h=104)
    svg.append('<text x="108" y="758" text-anchor="middle" font-size="15.5" font-weight="700" fill="#4A4A4A">Transactional</text>')
    svg.append('<text x="108" y="778" text-anchor="middle" font-size="15.5" font-weight="700" fill="#4A4A4A">Systems</text>')
    svg.append('<text x="108" y="796" text-anchor="middle" font-size="11.2" font-weight="500" fill="#5F6368">(Systems of Record)</text>')

    tx_x, tx_y, tx_w, tx_h = 216.0, 718.0, 1164.0, 104.0
    svg.append(
        f'<rect x="{tx_x:.1f}" y="{tx_y:.1f}" width="{tx_w:.1f}" height="{tx_h:.1f}" rx="18" '
        f'fill="#FFFFFF" stroke="#1F5A88" stroke-width="2.0"/>'
    )
    n_tx = max(len(tx_cards), 1)
    tx_pad = 22.0
    tx_gap = 14.0
    tc_w = (tx_w - 2 * tx_pad - (n_tx - 1) * tx_gap) / n_tx
    for idx, tc in enumerate(tx_cards):
        cx = tx_x + tx_pad + idx * (tc_w + tx_gap)
        svg.append(
            _draw_boxed_card(
                cx,
                tx_y + 18.0,
                tc_w,
                68.0,
                tc.get("line1", ""),
                tc.get("line2", ""),
                fill="#F8FAFC",
                stroke="#2C5E8A",
                badge_color="#34A853",
            )
        )

    svg.append("</svg>")
    return "\n".join(svg) + "\n"


def write_high_level_solution_svg_and_png(parsed: dict[str, Any], svg_path: Path) -> tuple[Path, Path | None]:
    return _save_svg_and_png(render_high_level_solution_svg(parsed), svg_path, width=1440, height=860)


def _icon_ai_sparkle(x: float, y: float) -> str:
    return (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<rect x="2" y="2" width="20" height="20" rx="5" fill="#F3E8FF" stroke="#7C3AED" stroke-width="1.5"/>'
        f'<path d="M12 5 L13.8 9.8 L18.5 11.5 L13.8 13.2 L12 18 L10.2 13.2 L5.5 11.5 L10.2 9.8 Z" fill="#7C3AED"/>'
        f'<circle cx="17.2" cy="6.8" r="1.3" fill="#00A1E0"/>'
        f"</g>"
    )


def _draw_modern_icon_card(
    x: float,
    y: float,
    w: float,
    h: float,
    line1: str,
    line2: str = "",
    icon_kind: str = "compute",
    stroke: str = "#1A73E8",
    badge_bg: str = "#E8F0FE",
    step_num: int | None = None,
) -> str:
    """Renders a high-legibility left-icon enterprise component card with bold title, subtitle, and optional step badge."""
    parts: list[str] = [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" '
        f'fill="#FFFFFF" stroke="{stroke}" stroke-width="1.8"/>',
        f'<rect x="{x + 1.0:.1f}" y="{y + 1.0:.1f}" width="6.0" height="{h - 2.0:.1f}" rx="3" fill="{stroke}"/>',
    ]
    ic_box = 34.0
    ic_x = x + 14.0
    ic_y = y + (h - ic_box) / 2.0
    parts.append(
        f'<rect x="{ic_x:.1f}" y="{ic_y:.1f}" width="{ic_box:.1f}" height="{ic_box:.1f}" rx="8" '
        f'fill="{badge_bg}" stroke="{stroke}" stroke-width="1.0"/>'
    )
    if icon_kind == "ai":
        parts.append(_icon_ai_sparkle(ic_x + 5.0, ic_y + 5.0))
    else:
        parts.append(_render_icon(icon_kind, ic_x + 5.0, ic_y + 5.0))

    if step_num is not None:
        parts.append(
            f'<circle cx="{x + w - 16.0:.1f}" cy="{y + 16.0:.1f}" r="10.0" fill="{stroke}"/>'
            f'<text x="{x + w - 16.0:.1f}" y="{y + 20.0:.1f}" text-anchor="middle" font-size="10.5" font-weight="700" fill="#FFFFFF">{step_num}</text>'
        )

    tx = ic_x + ic_box + 11.0
    avail_w = w - (tx - x) - (26.0 if step_num is not None else 10.0)
    max_c1 = max(14, int(avail_w / 6.8))
    max_c2 = max(16, int(avail_w / 5.6))
    l1_lines = _wrap_lines(line1, max_chars=max_c1, max_lines=2)
    l2_lines = _wrap_lines(line2, max_chars=max_c2, max_lines=2) if line2 else []

    if len(l1_lines) == 1:
        parts.append(
            f'<text x="{tx:.1f}" y="{y + h / 2.0 - (6.0 if l2_lines else -4.0):.1f}" '
            f'font-size="13.2" font-weight="700" fill="#1E293B">{_esc(l1_lines[0])}</text>'
        )
        if len(l2_lines) == 1:
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 12.0:.1f}" '
                f'font-size="11.2" font-weight="500" fill="#475569">{_esc(l2_lines[0])}</text>'
            )
        elif len(l2_lines) >= 2:
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 9.0:.1f}" '
                f'font-size="10.6" font-weight="500" fill="#475569">{_esc(l2_lines[0])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 22.0:.1f}" '
                f'font-size="10.6" font-weight="500" fill="#475569">{_esc(l2_lines[1])}</text>'
            )
    else:
        if len(l2_lines) <= 1:
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 - 13.0:.1f}" '
                f'font-size="12.4" font-weight="700" fill="#1E293B">{_esc(l1_lines[0])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 1.0:.1f}" '
                f'font-size="12.4" font-weight="700" fill="#1E293B">{_esc(l1_lines[1])}</text>'
            )
            if l2_lines:
                parts.append(
                    f'<text x="{tx:.1f}" y="{y + h / 2.0 + 17.0:.1f}" '
                    f'font-size="10.6" font-weight="500" fill="#475569">{_esc(l2_lines[0])}</text>'
                )
        else:
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 - 18.0:.1f}" '
                f'font-size="12.1" font-weight="700" fill="#1E293B">{_esc(l1_lines[0])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 - 4.5:.1f}" '
                f'font-size="12.1" font-weight="700" fill="#1E293B">{_esc(l1_lines[1])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 9.5:.1f}" '
                f'font-size="10.3" font-weight="500" fill="#475569">{_esc(l2_lines[0])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 21.5:.1f}" '
                f'font-size="10.3" font-weight="500" fill="#475569">{_esc(l2_lines[1])}</text>'
            )
    return "\n".join(parts)


def _draw_cylinder_store_card(
    x: float,
    y: float,
    w: float,
    h: float,
    line1: str,
    line2: str = "",
    cyl_fill: str = "#D1FAE5",
    cyl_top: str = "#6EE7B7",
    stroke: str = "#059669",
) -> str:
    """Renders a Data Architecture card with a 3D Database Cylinder graphic on the left."""
    parts: list[str] = [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" '
        f'fill="#FFFFFF" stroke="{stroke}" stroke-width="1.8"/>'
    ]
    cx = x + 28.0
    cy_top = y + 22.0
    cy_bot = y + h - 18.0
    rx = 16.0
    ry = 6.5
    parts += [
        f'<path d="M {cx - rx:.1f} {cy_top:.1f} L {cx - rx:.1f} {cy_bot:.1f} '
        f'A {rx:.1f} {ry:.1f} 0 0 0 {cx + rx:.1f} {cy_bot:.1f} L {cx + rx:.1f} {cy_top:.1f} Z" '
        f'fill="{cyl_fill}" stroke="{stroke}" stroke-width="1.6"/>',
        f'<ellipse cx="{cx:.1f}" cy="{cy_top:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
        f'fill="{cyl_top}" stroke="{stroke}" stroke-width="1.6"/>',
        f'<path d="M {cx - rx:.1f} {(cy_top + cy_bot) / 2.0:.1f} '
        f'A {rx:.1f} {ry:.1f} 0 0 0 {cx + rx:.1f} {(cy_top + cy_bot) / 2.0:.1f}" '
        f'fill="none" stroke="{stroke}" stroke-width="1.3"/>',
        f'<circle cx="{cx + 8.0:.1f}" cy="{cy_top + 13.0:.1f}" r="2.2" fill="{stroke}"/>',
        f'<circle cx="{cx + 8.0:.1f}" cy="{cy_bot - 6.0:.1f}" r="2.2" fill="{stroke}"/>',
    ]
    tx = x + 54.0
    avail_w = w - 62.0
    max_c1 = max(13, int(avail_w / 6.8))
    max_c2 = max(15, int(avail_w / 5.5))
    l1_lines = _wrap_lines(line1, max_chars=max_c1, max_lines=2)
    l2_lines = _wrap_lines(line2, max_chars=max_c2, max_lines=2) if line2 else []
    if len(l1_lines) == 1:
        if len(l2_lines) <= 1:
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 - 5.0:.1f}" font-size="12.8" font-weight="700" fill="#1E293B">{_esc(l1_lines[0])}</text>'
            )
            if l2_lines:
                parts.append(
                    f'<text x="{tx:.1f}" y="{y + h / 2.0 + 12.0:.1f}" font-size="10.8" font-weight="500" fill="#475569">{_esc(l2_lines[0])}</text>'
                )
        else:
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 - 10.0:.1f}" font-size="12.6" font-weight="700" fill="#1E293B">{_esc(l1_lines[0])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 5.5:.1f}" font-size="10.4" font-weight="500" fill="#475569">{_esc(l2_lines[0])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 18.0:.1f}" font-size="10.4" font-weight="500" fill="#475569">{_esc(l2_lines[1])}</text>'
            )
    else:
        if len(l2_lines) <= 1:
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 - 12.0:.1f}" font-size="12.0" font-weight="700" fill="#1E293B">{_esc(l1_lines[0])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 2.0:.1f}" font-size="12.0" font-weight="700" fill="#1E293B">{_esc(l1_lines[1])}</text>'
            )
            if l2_lines:
                parts.append(
                    f'<text x="{tx:.1f}" y="{y + h / 2.0 + 17.0:.1f}" font-size="10.3" font-weight="500" fill="#475569">{_esc(l2_lines[0])}</text>'
                )
        else:
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 - 17.5:.1f}" font-size="11.8" font-weight="700" fill="#1E293B">{_esc(l1_lines[0])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 - 4.0:.1f}" font-size="11.8" font-weight="700" fill="#1E293B">{_esc(l1_lines[1])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 9.5:.1f}" font-size="10.1" font-weight="500" fill="#475569">{_esc(l2_lines[0])}</text>'
            )
            parts.append(
                f'<text x="{tx:.1f}" y="{y + h / 2.0 + 21.0:.1f}" font-size="10.1" font-weight="500" fill="#475569">{_esc(l2_lines[1])}</text>'
            )
    return "\n".join(parts)


def render_application_architecture_svg(parsed: dict[str, Any]) -> str:
    """Renders a crystal-clear C4 Application & AI Component Architecture SVG (`1440x860`).

    Layout:
    - Left-Margin Layer Labels (`Presentation Layer`, `API & BFF Gateway`, `Domain & AI Services`, `Data & Integration`)
    - Band 1: Presentation & Omnichannel UI Modules (4 icon-badged UI workspace cards)
    - Protocol Spine 1: `HTTPS / REST JSON · Role-Scoped UI Actions`
    - Band 2: API Gateway, BFF & Zero-Leak DTO Pipeline (`[1] Router -> [2] RBAC/State Guard -> [3] Validator -> [4] Zero-Leak DTO`)
    - Protocol Spine 2: Split flow into `Validated Domain Commands` (left) & `Grounded RAG Queries` (right)
    - Band 3: Split Container — Left: `Core Domain & Workflow Microservices` (3 large service cards) | Right: `Agentic AI & Copilot Runtime`
    - Protocol Spine 3: `ACID SQL Unit-of-Work · Transactional Outbox · Append-Only Audit`
    - Band 4: Data Access Repositories & Integration Adapters (4 icon-badged repository/adapter cards)
    """
    title = str(parsed.get("title") or "Application & AI Component Architecture").strip()
    root_sgs = parsed.get("rootSubgraphs") or []
    if len(root_sgs) == 1 and len(root_sgs[0].get("children") or []) >= 3:
        tiers = root_sgs[0]["children"]
    else:
        tiers = root_sgs

    def _tier_cards(idx: int) -> list[dict[str, Any]]:
        if idx >= len(tiers):
            return []
        t_sg = tiers[idx]
        out = list(t_sg.get("cards") or [])
        for ch in t_sg.get("children") or []:
            out.extend(ch.get("cards") or [])
        return out

    t1_cards = _tier_cards(0)[:4]
    t2_cards = _tier_cards(1)[:4]
    t3_cards = _tier_cards(2)[:4]
    t4_cards = _tier_cards(3)[:4]

    svg: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 860" width="1440" height="860" '
        'font-family="\'Google Sans\', \'Roboto\', \'Inter\', -apple-system, BlinkMacSystemFont, \'Segoe UI\', Arial, sans-serif">',
        "<defs>",
        '  <marker id="appArrowBlue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#1A73E8"/>',
        "  </marker>",
        '  <marker id="appArrowGreen" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#059669"/>',
        "  </marker>",
        '  <marker id="appArrowPurple" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#7C3AED"/>',
        "  </marker>",
        '  <marker id="appArrowAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#D97706"/>',
        "  </marker>",
        "</defs>",
        '<rect x="0" y="0" width="1440" height="860" fill="#FFFFFF"/>',
        f'<text x="48" y="54" font-size="28" font-weight="700" fill="#202124">{_esc(title)}</text>',
        '<text x="48" y="78" font-size="13.5" font-weight="500" fill="#5F6368">C4 Application Component Topology: Presentation Workspaces → API &amp; Zero-Leak BFF Pipeline → Domain Microservices &amp; Agentic AI → Repositories &amp; Outbox</text>',
    ]

    bx = 216.0
    bw = 1184.0

    # --- TIER 1: Presentation & Omnichannel UI Modules (y=104, h=132) ---
    svg.append('<text x="108" y="158" text-anchor="middle" font-size="15.0" font-weight="700" fill="#1E3A8A">Presentation</text>')
    svg.append('<text x="108" y="177" text-anchor="middle" font-size="15.0" font-weight="700" fill="#1E3A8A">&amp; UI Tier</text>')
    svg.append('<text x="108" y="195" text-anchor="middle" font-size="11.2" font-weight="500" fill="#475569">(WCAG 2.1 AA · M3)</text>')

    t1_y, t1_h = 104.0, 132.0
    svg.append(
        f'<rect x="{bx:.1f}" y="{t1_y:.1f}" width="{bw:.1f}" height="{t1_h:.1f}" rx="14" '
        f'fill="#EFF6FF" stroke="#1A73E8" stroke-width="2.2"/>'
    )
    svg.append(
        f'<text x="{bx + 20:.1f}" y="{t1_y + 25:.1f}" font-size="13.8" font-weight="700" fill="#1E40AF">'
        f'1. Presentation &amp; Omnichannel Experience Modules (Role-Separated Views &amp; AI Assistant Drawer)</text>'
    )
    n1 = max(len(t1_cards), 1)
    c1_gap = 16.0
    c1_w = (bw - 40.0 - (n1 - 1) * c1_gap) / n1
    for i, c in enumerate(t1_cards):
        cx = bx + 20.0 + i * (c1_w + c1_gap)
        ic_kind = "ai" if "copilot" in c.get("line1", "").lower() or "ai" in c.get("line1", "").lower() else "ui"
        svg.append(
            _draw_modern_icon_card(
                cx,
                t1_y + 38.0,
                c1_w,
                78.0,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=ic_kind,
                stroke="#1A73E8",
                badge_bg="#DBEAFE",
            )
        )

    # Connector T1 -> T2
    for ax in (410.0, 808.0, 1206.0):
        svg.append(
            f'<line x1="{ax:.1f}" y1="{t1_y + t1_h:.1f}" x2="{ax:.1f}" y2="274.0" '
            f'stroke="#1A73E8" stroke-width="2.2" marker-end="url(#appArrowBlue)"/>'
        )
    svg.append('<rect x="618" y="243" width="380" height="24" rx="12" fill="#E0F2FE" stroke="#0284C7" stroke-width="1.2"/>')
    svg.append('<text x="808" y="259" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0369A1">HTTPS / JSON REST · Role-Scoped UI Actions</text>')

    # --- TIER 2: API Gateway, BFF & Zero-Leak DTO Pipeline (y=278, h=136) ---
    svg.append('<text x="108" y="334" text-anchor="middle" font-size="15.0" font-weight="700" fill="#0369A1">API Gateway</text>')
    svg.append('<text x="108" y="353" text-anchor="middle" font-size="15.0" font-weight="700" fill="#0369A1">&amp; BFF Tier</text>')
    svg.append('<text x="108" y="371" text-anchor="middle" font-size="11.2" font-weight="500" fill="#475569">(OpenAPI 3.1 · Zero-Leak)</text>')

    t2_y, t2_h = 278.0, 136.0
    svg.append(
        f'<rect x="{bx:.1f}" y="{t2_y:.1f}" width="{bw:.1f}" height="{t2_h:.1f}" rx="14" '
        f'fill="#F0F9FF" stroke="#0284C7" stroke-width="2.2"/>'
    )
    svg.append(
        f'<text x="{bx + 20:.1f}" y="{t2_y + 25:.1f}" font-size="13.8" font-weight="700" fill="#0369A1">'
        f'2. API Contract Mediation, RBAC/State Guard &amp; Zero-Leak ViewModel/DTO Pipeline (Sequential Request Filter)</text>'
    )
    n2 = max(len(t2_cards), 1)
    c2_gap = 24.0
    c2_w = (bw - 40.0 - (n2 - 1) * c2_gap) / n2
    t2_icons = ["network", "security", "rules", "security"]
    for i, c in enumerate(t2_cards):
        cx = bx + 20.0 + i * (c2_w + c2_gap)
        svg.append(
            _draw_modern_icon_card(
                cx,
                t2_y + 40.0,
                c2_w,
                80.0,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=t2_icons[i % len(t2_icons)],
                stroke="#0284C7",
                badge_bg="#E0F2FE",
                step_num=i + 1,
            )
        )
        if i < n2 - 1:
            ax0 = cx + c2_w + 2.0
            ax1 = cx + c2_w + c2_gap - 4.0
            ay = t2_y + 80.0
            svg.append(
                f'<line x1="{ax0:.1f}" y1="{ay:.1f}" x2="{ax1:.1f}" y2="{ay:.1f}" '
                f'stroke="#0284C7" stroke-width="2.0" marker-end="url(#appArrowBlue)"/>'
            )

    # Connector T2 -> T3 (Split into Core Domain Services left & Agentic AI Runtime right)
    svg.append('<line x1="630" y1="414" x2="630" y2="454" stroke="#059669" stroke-width="2.4" marker-end="url(#appArrowGreen)"/>')
    svg.append('<rect x="465" y="422" width="330" height="24" rx="12" fill="#DCFCE7" stroke="#059669" stroke-width="1.2"/>')
    svg.append('<text x="630" y="438" text-anchor="middle" font-size="11.5" font-weight="700" fill="#047857">Validated Domain Commands &amp; State Transitions</text>')

    svg.append('<line x1="1238" y1="414" x2="1238" y2="454" stroke="#7C3AED" stroke-width="2.4" marker-end="url(#appArrowPurple)"/>')
    svg.append('<rect x="1118" y="422" width="240" height="24" rx="12" fill="#F3E8FF" stroke="#7C3AED" stroke-width="1.2"/>')
    svg.append('<text x="1238" y="438" text-anchor="middle" font-size="11.5" font-weight="700" fill="#6D28D9">Read-Only Grounded RAG</text>')

    # --- TIER 3: Split Core Domain Microservices (Left) + Agentic AI Runtime (Right) (y=458, h=188) ---
    svg.append('<text x="108" y="538" text-anchor="middle" font-size="15.0" font-weight="700" fill="#047857">Domain &amp; AI</text>')
    svg.append('<text x="108" y="557" text-anchor="middle" font-size="15.0" font-weight="700" fill="#047857">Services Tier</text>')
    svg.append('<text x="108" y="575" text-anchor="middle" font-size="11.2" font-weight="500" fill="#475569">(Stateless Core + RAG)</text>')

    t3_y, t3_h = 458.0, 188.0
    dom_w = 842.0
    ai_x = bx + dom_w + 20.0
    ai_w = bw - dom_w - 20.0

    # Separate AI card vs Domain cards in Tier 3
    ai_card = None
    dom_cards: list[dict[str, Any]] = []
    for c in t3_cards:
        lbl = f"{c.get('line1', '')} {c.get('line2', '')}".lower()
        if ("ai " in lbl or "agent" in lbl or "rag" in lbl or "copilot" in lbl) and ai_card is None:
            ai_card = c
        else:
            dom_cards.append(c)
    if ai_card is None and dom_cards:
        ai_card = dom_cards.pop()
    dom_cards = dom_cards[:3]

    svg.append(
        f'<rect x="{bx:.1f}" y="{t3_y:.1f}" width="{dom_w:.1f}" height="{t3_h:.1f}" rx="14" '
        f'fill="#ECFDF5" stroke="#059669" stroke-width="2.4"/>'
    )
    svg.append(
        f'<text x="{bx + 20:.1f}" y="{t3_y + 26:.1f}" font-size="13.8" font-weight="700" fill="#065F46">'
        f'3A. Core Domain &amp; Workflow Services (Deterministic State Machine, Business Rules &amp; Escalation)</text>'
    )
    nd = max(len(dom_cards), 1)
    cd_gap = 16.0
    cd_w = (dom_w - 40.0 - (nd - 1) * cd_gap) / nd
    dom_icons = ["workflow", "rules", "compute"]
    for i, c in enumerate(dom_cards):
        cx = bx + 20.0 + i * (cd_w + cd_gap)
        svg.append(
            _draw_modern_icon_card(
                cx,
                t3_y + 42.0,
                cd_w,
                92.0,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=dom_icons[i % len(dom_icons)],
                stroke="#059669",
                badge_bg="#D1FAE5",
            )
        )
    svg.append(
        f'<rect x="{bx + 20:.1f}" y="{t3_y + 146.0:.1f}" width="{dom_w - 40.0:.1f}" height="28.0" rx="8" '
        f'fill="#D1FAE5" stroke="#059669" stroke-width="1.2"/>'
        f'<text x="{bx + dom_w / 2.0:.1f}" y="{t3_y + 164.5:.1f}" text-anchor="middle" font-size="11.5" font-weight="700" fill="#065F46">'
        f'✓ Enforces Lifecycle State Table   ·   ✓ Deterministic Calculations   ·   ✓ Separation-of-Duties Guards</text>'
    )

    # Right sub-container: Agentic AI & RAG Runtime
    svg.append(
        f'<rect x="{ai_x:.1f}" y="{t3_y:.1f}" width="{ai_w:.1f}" height="{t3_h:.1f}" rx="14" '
        f'fill="#F5F3FF" stroke="#7C3AED" stroke-width="2.4"/>'
    )
    svg.append(
        f'<text x="{ai_x + 18:.1f}" y="{t3_y + 26:.1f}" font-size="13.8" font-weight="700" fill="#5B21B6">'
        f'3B. Agentic AI &amp; RAG Runtime</text>'
    )
    if ai_card:
        svg.append(
            _draw_modern_icon_card(
                ai_x + 16.0,
                t3_y + 42.0,
                ai_w - 32.0,
                92.0,
                ai_card.get("line1", "Domain AI Agent"),
                ai_card.get("line2", "Grounded Policy RAG"),
                icon_kind="ai",
                stroke="#7C3AED",
                badge_bg="#EDE9FE",
            )
        )
    svg.append(
        f'<rect x="{ai_x + 16.0:.1f}" y="{t3_y + 146.0:.1f}" width="{ai_w - 32.0:.1f}" height="28.0" rx="8" '
        f'fill="#EDE9FE" stroke="#7C3AED" stroke-width="1.2"/>'
        f'<text x="{ai_x + ai_w / 2.0:.1f}" y="{t3_y + 164.5:.1f}" text-anchor="middle" font-size="11.2" font-weight="700" fill="#5B21B6">'
        f'✓ Cited RAG · ✓ Human-in-the-Loop</text>'
    )

    # Connector T3 -> T4
    for ax in (410.0, 808.0, 1206.0):
        svg.append(
            f'<line x1="{ax:.1f}" y1="{t3_y + t3_h:.1f}" x2="{ax:.1f}" y2="686.0" '
            f'stroke="#D97706" stroke-width="2.2" marker-end="url(#appArrowAmber)"/>'
        )
    svg.append('<rect x="578" y="654" width="460" height="24" rx="12" fill="#FEF3C7" stroke="#D97706" stroke-width="1.2"/>')
    svg.append('<text x="808" y="670" text-anchor="middle" font-size="11.5" font-weight="700" fill="#B45309">ACID SQL Unit-of-Work · Transactional Event Outbox · Append-Only Audit</text>')

    # --- TIER 4: Data Access Repositories & Integration Adapters (y=690, h=136) ---
    svg.append('<text x="108" y="746" text-anchor="middle" font-size="15.0" font-weight="700" fill="#B45309">Data Access &amp;</text>')
    svg.append('<text x="108" y="765" text-anchor="middle" font-size="15.0" font-weight="700" fill="#B45309">Adapters Tier</text>')
    svg.append('<text x="108" y="783" text-anchor="middle" font-size="11.2" font-weight="500" fill="#475569">(Parameterized SQL)</text>')

    t4_y, t4_h = 690.0, 136.0
    svg.append(
        f'<rect x="{bx:.1f}" y="{t4_y:.1f}" width="{bw:.1f}" height="{t4_h:.1f}" rx="14" '
        f'fill="#FFFBEB" stroke="#D97706" stroke-width="2.2"/>'
    )
    svg.append(
        f'<text x="{bx + 20:.1f}" y="{t4_y + 25:.1f}" font-size="13.8" font-weight="700" fill="#B45309">'
        f'4. Data Access Repositories, Cryptographic Adapters &amp; Outbound Integration Ports</text>'
    )
    n4 = max(len(t4_cards), 1)
    c4_gap = 16.0
    c4_w = (bw - 40.0 - (n4 - 1) * c4_gap) / n4
    t4_icons = ["database", "network", "security", "observability"]
    for i, c in enumerate(t4_cards):
        cx = bx + 20.0 + i * (c4_w + c4_gap)
        svg.append(
            _draw_modern_icon_card(
                cx,
                t4_y + 38.0,
                c4_w,
                80.0,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=t4_icons[i % len(t4_icons)],
                stroke="#D97706",
                badge_bg="#FEF3C7",
            )
        )

    svg.append("</svg>")
    return "\n".join(svg) + "\n"


def write_application_architecture_svg_and_png(parsed: dict[str, Any], svg_path: Path) -> tuple[Path, Path | None]:
    return _save_svg_and_png(render_application_architecture_svg(parsed), svg_path, width=1440, height=860)


def render_data_architecture_svg(parsed: dict[str, Any]) -> str:
    """Renders an unmistakable, high-legibility Data & AI Grounding Architecture SVG (`1440x860`).

    Layout:
    - Column 1 (`w=286`): `1. Data Sources & Producers` (4 wide left-icon cards)
    - Column 2 (`w=286`): `2. Ingestion, Validation & CDC` (4 sequential pipeline cards `1 -> 2 -> 3 -> 4` with vertical flow arrows)
    - Center Split Core (`w=396`):
      - Top Container (`3. Operational 3NF System of Record`): 2x2 grid of **3D Database Cylinder Cards** (ACID Primary, HA Standby, Master Lookup, Append-Only Audit)
      - Bottom Container (`4. Unified Data Mart & AI Grounding`): 2x2 grid of **3D Analytical/Vector Cylinder Cards** (Curated Mart, Vector RAG Index, Semantic Layer, De-Identified Analytics)
    - Column 4 (`w=286`): `5. Consumption, Analytics & Export` (4 wide consumer cards with icons)
    - Bottom Full-Width Bar: `Unified Data Governance, Lineage, PII Masking, KMS Encryption & Statutory Retention`
    """
    title = str(parsed.get("title") or "End-to-End Data & AI Grounding Architecture").strip()
    root_sgs = parsed.get("rootSubgraphs") or []
    if len(root_sgs) == 1 and len(root_sgs[0].get("children") or []) >= 3:
        sgs = root_sgs[0]["children"]
    else:
        sgs = root_sgs

    gov_sg = None
    stages: list[dict[str, Any]] = []
    for sg in sgs:
        if "gov" in sg.get("id", "").lower() or "governance" in sg.get("title", "").lower():
            gov_sg = sg
        else:
            stages.append(sg)

    def _st_cards(idx: int) -> list[dict[str, Any]]:
        if idx >= len(stages):
            return []
        st = stages[idx]
        out = list(st.get("cards") or [])
        for ch in st.get("children") or []:
            out.extend(ch.get("cards") or [])
        return out[:4]

    s1_cards = _st_cards(0)
    s2_cards = _st_cards(1)
    s3_cards = _st_cards(2)
    s4_cards = _st_cards(3)
    s5_cards = _st_cards(4)

    svg: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 860" width="1440" height="860" '
        'font-family="\'Google Sans\', \'Roboto\', \'Inter\', -apple-system, BlinkMacSystemFont, \'Segoe UI\', Arial, sans-serif">',
        "<defs>",
        '  <marker id="dataArrBlue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#2563EB"/>',
        "  </marker>",
        '  <marker id="dataArrGreen" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#059669"/>',
        "  </marker>",
        '  <marker id="dataArrPurple" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#7C3AED"/>',
        "  </marker>",
        '  <marker id="dataArrAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#D97706"/>',
        "  </marker>",
        "</defs>",
        '<rect x="0" y="0" width="1440" height="860" fill="#FFFFFF"/>',
        f'<text x="44" y="54" font-size="28" font-weight="700" fill="#202124">{_esc(title)}</text>',
        '<text x="44" y="78" font-size="13.5" font-weight="500" fill="#5F6368">End-to-End Information Pipeline: Producers → Validation &amp; Tokenization → 3NF Relational Core &amp; Vector RAG Stores → Consumers &amp; Governance</text>',
    ]

    top_y = 104.0
    col_h = 576.0

    # --- COLUMN 1: Data Sources & Producers (x=44, w=276) ---
    c1_x, c1_w = 44.0, 276.0
    svg.append(
        f'<rect x="{c1_x:.1f}" y="{top_y:.1f}" width="{c1_w:.1f}" height="{col_h:.1f}" rx="14" '
        f'fill="#F8FAFC" stroke="#475569" stroke-width="2.2"/>'
        f'<text x="{c1_x + c1_w / 2.0:.1f}" y="{top_y + 28:.1f}" text-anchor="middle" font-size="14.2" font-weight="700" fill="#1E293B">'
        f'1. Data Sources &amp; Producers</text>'
    )
    s1_icons = ["ui", "database", "storage", "compute"]
    for i, c in enumerate(s1_cards):
        cy = top_y + 50.0 + i * 126.0
        svg.append(
            _draw_modern_icon_card(
                c1_x + 14.0,
                cy,
                c1_w - 28.0,
                104.0,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=s1_icons[i % len(s1_icons)],
                stroke="#475569",
                badge_bg="#E2E8F0",
            )
        )

    # Arrow Col 1 -> Col 2
    svg.append(
        f'<line x1="{c1_x + c1_w + 2:.1f}" y1="{top_y + col_h / 2.0:.1f}" x2="350.0" y2="{top_y + col_h / 2.0:.1f}" '
        f'stroke="#2563EB" stroke-width="2.8" marker-end="url(#dataArrBlue)"/>'
    )

    # --- COLUMN 2: Ingestion, Validation & CDC Pipeline (x=354, w=276) ---
    c2_x, c2_w = 354.0, 276.0
    svg.append(
        f'<rect x="{c2_x:.1f}" y="{top_y:.1f}" width="{c2_w:.1f}" height="{col_h:.1f}" rx="14" '
        f'fill="#EFF6FF" stroke="#2563EB" stroke-width="2.2"/>'
        f'<text x="{c2_x + c2_w / 2.0:.1f}" y="{top_y + 28:.1f}" text-anchor="middle" font-size="14.2" font-weight="700" fill="#1D4ED8">'
        f'2. Ingestion, Validation &amp; CDC</text>'
    )
    s2_icons = ["rules", "workflow", "security", "network"]
    for i, c in enumerate(s2_cards):
        cy = top_y + 50.0 + i * 126.0
        svg.append(
            _draw_modern_icon_card(
                c2_x + 14.0,
                cy,
                c2_w - 28.0,
                100.0,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=s2_icons[i % len(s2_icons)],
                stroke="#2563EB",
                badge_bg="#DBEAFE",
                step_num=i + 1,
            )
        )
        if i < len(s2_cards) - 1:
            ay0 = cy + 100.0 + 2.0
            ay1 = cy + 126.0 - 4.0
            ax = c2_x + c2_w / 2.0
            svg.append(
                f'<line x1="{ax:.1f}" y1="{ay0:.1f}" x2="{ax:.1f}" y2="{ay1:.1f}" '
                f'stroke="#2563EB" stroke-width="2.0" marker-end="url(#dataArrBlue)"/>'
            )

    # Arrow Col 2 -> Center Top (3NF System of Record)
    svg.append(
        f'<line x1="{c2_x + c2_w + 2:.1f}" y1="{top_y + 140.0:.1f}" x2="660.0" y2="{top_y + 140.0:.1f}" '
        f'stroke="#059669" stroke-width="2.8" marker-end="url(#dataArrGreen)"/>'
    )

    # --- CENTER SPLIT CORE (x=664, w=420): Top = 3NF System of Record Cylinders | Bottom = AI & Analytical Cylinders ---
    c3_x, c3_w = 664.0, 420.0
    box_h = 272.0

    # 3A. Top Box: Operational 3NF System of Record (y=104, h=272)
    svg.append(
        f'<rect x="{c3_x:.1f}" y="{top_y:.1f}" width="{c3_w:.1f}" height="{box_h:.1f}" rx="14" '
        f'fill="#ECFDF5" stroke="#059669" stroke-width="2.4"/>'
        f'<text x="{c3_x + c3_w / 2.0:.1f}" y="{top_y + 26:.1f}" text-anchor="middle" font-size="14.2" font-weight="700" fill="#065F46">'
        f'3. Operational 3NF System of Record (ACID Stores)</text>'
    )
    cell_w = (c3_w - 40.0) / 2.0
    cell_h = 98.0
    for i, c in enumerate(s3_cards[:4]):
        row = i // 2
        col = i % 2
        cx = c3_x + 14.0 + col * (cell_w + 12.0)
        cy = top_y + 42.0 + row * (cell_h + 14.0)
        svg.append(
            _draw_cylinder_store_card(
                cx,
                cy,
                cell_w,
                cell_h,
                c.get("line1", ""),
                c.get("line2", ""),
                cyl_fill="#D1FAE5",
                cyl_top="#6EE7B7",
                stroke="#059669",
            )
        )

    # Arrow from 3NF System of Record down to Unified Data & AI Grounding
    mid_cx = c3_x + c3_w / 2.0
    svg.append(
        f'<line x1="{mid_cx:.1f}" y1="{top_y + box_h:.1f}" x2="{mid_cx:.1f}" y2="{top_y + box_h + 28.0:.1f}" '
        f'stroke="#7C3AED" stroke-width="2.6" marker-end="url(#dataArrPurple)"/>'
    )
    svg.append(
        f'<rect x="{mid_cx - 115.0:.1f}" y="{top_y + box_h + 5.0:.1f}" width="230.0" height="20.0" rx="10" '
        f'fill="#F3E8FF" stroke="#7C3AED" stroke-width="1.1"/>'
        f'<text x="{mid_cx:.1f}" y="{top_y + box_h + 18.5:.1f}" text-anchor="middle" font-size="10.5" font-weight="700" fill="#6D28D9">'
        f'CDC Stream &amp; Vector Embeddings</text>'
    )

    # 3B. Bottom Box: Unified Data Mart & AI Grounding (y=408, h=272)
    b4_y = top_y + box_h + 32.0
    svg.append(
        f'<rect x="{c3_x:.1f}" y="{b4_y:.1f}" width="{c3_w:.1f}" height="{box_h:.1f}" rx="14" '
        f'fill="#F5F3FF" stroke="#7C3AED" stroke-width="2.4"/>'
        f'<text x="{c3_x + c3_w / 2.0:.1f}" y="{b4_y + 26:.1f}" text-anchor="middle" font-size="14.2" font-weight="700" fill="#5B21B6">'
        f'4. Curated Data Marts &amp; AI RAG Grounding</text>'
    )
    for i, c in enumerate(s4_cards[:4]):
        row = i // 2
        col = i % 2
        cx = c3_x + 14.0 + col * (cell_w + 12.0)
        cy = b4_y + 42.0 + row * (cell_h + 14.0)
        svg.append(
            _draw_cylinder_store_card(
                cx,
                cy,
                cell_w,
                cell_h,
                c.get("line1", ""),
                c.get("line2", ""),
                cyl_fill="#EDE9FE",
                cyl_top="#C4B5FD",
                stroke="#7C3AED",
            )
        )

    # Arrows from 3NF & AI Grounding -> Column 5 (Consumers)
    svg.append(
        f'<line x1="{c3_x + c3_w + 2:.1f}" y1="{top_y + 140.0:.1f}" x2="1114.0" y2="{top_y + 140.0:.1f}" '
        f'stroke="#D97706" stroke-width="2.8" marker-end="url(#dataArrAmber)"/>'
    )
    svg.append(
        f'<line x1="{c3_x + c3_w + 2:.1f}" y1="{b4_y + 140.0:.1f}" x2="1114.0" y2="{b4_y + 140.0:.1f}" '
        f'stroke="#D97706" stroke-width="2.8" marker-end="url(#dataArrAmber)"/>'
    )

    # --- COLUMN 5: Consumption, Analytics & Export (x=1118, w=278) ---
    c5_x, c5_w = 1118.0, 278.0
    svg.append(
        f'<rect x="{c5_x:.1f}" y="{top_y:.1f}" width="{c5_w:.1f}" height="{col_h:.1f}" rx="14" '
        f'fill="#FFFBEB" stroke="#D97706" stroke-width="2.2"/>'
        f'<text x="{c5_x + c5_w / 2.0:.1f}" y="{top_y + 28:.1f}" text-anchor="middle" font-size="14.2" font-weight="700" fill="#B45309">'
        f'5. Consumption &amp; Export</text>'
    )
    s5_icons = ["security", "observability", "ai", "network"]
    for i, c in enumerate(s5_cards):
        cy = top_y + 50.0 + i * 126.0
        svg.append(
            _draw_modern_icon_card(
                c5_x + 14.0,
                cy,
                c5_w - 28.0,
                104.0,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=s5_icons[i % len(s5_icons)],
                stroke="#D97706",
                badge_bg="#FEF3C7",
            )
        )

    # --- BOTTOM BAR: Unified Data Governance, Lineage, PII Masking & Retention (y=702, h=126) ---
    gov_y, gov_h = 702.0, 126.0
    total_w = 1352.0
    svg.append(
        f'<rect x="44.0" y="{gov_y:.1f}" width="{total_w:.1f}" height="{gov_h:.1f}" rx="14" '
        f'fill="#F1F5F9" stroke="#0F172A" stroke-width="2.2"/>'
    )
    gov_title = (
        gov_sg.get("title", "Unified Data Governance, Lineage, PII Masking, KMS Encryption & Statutory Retention")
        if gov_sg
        else "Unified Data Governance, Lineage, PII Masking, KMS Encryption & Statutory Retention"
    )
    svg.append(
        f'<text x="64.0" y="{gov_y + 26:.1f}" font-size="14.2" font-weight="700" fill="#0F172A">{_esc(gov_title)}</text>'
    )
    gov_cards = (gov_sg.get("cards") if gov_sg else None) or [
        {"line1": "Data Catalog & Lineage", "line2": "3NF Schema & Constraint Registry"},
        {"line1": "Zero-Leak PII Masking", "line2": "Role-Based Redaction & Tokenization"},
        {"line1": "KMS Encryption (CMEK)", "line2": "TLS 1.3 in Transit & AES-256 at Rest"},
        {"line1": "Retention & Archival", "line2": "Immutable Audit & 7-Year Lifecycle"},
    ]
    n_gc = max(len(gov_cards[:4]), 1)
    gc_w = (total_w - 40.0 - (n_gc - 1) * 16.0) / n_gc
    gov_icons = ["rules", "security", "security", "storage"]
    for i, gc in enumerate(gov_cards[:4]):
        gx = 64.0 + i * (gc_w + 16.0)
        svg.append(
            _draw_modern_icon_card(
                gx,
                gov_y + 38.0,
                gc_w,
                74.0,
                gc.get("line1", ""),
                gc.get("line2", ""),
                icon_kind=gov_icons[i % len(gov_icons)],
                stroke="#334155",
                badge_bg="#E2E8F0",
            )
        )

    svg.append("</svg>")
    return "\n".join(svg) + "\n"


def write_data_architecture_svg_and_png(parsed: dict[str, Any], svg_path: Path) -> tuple[Path, Path | None]:
    return _save_svg_and_png(render_data_architecture_svg(parsed), svg_path, width=1440, height=860)


def render_security_architecture_svg(parsed: dict[str, Any]) -> str:
    """Renders an unmistakable Zero-Trust Security & AI Trust Enclave Architecture SVG (`1440x860`).

    Layout:
    - Left-to-Right Zero-Trust Inspection Pipeline across 5 Concentric Perimeters:
      - Gate 1 (Column 1, Blue `#EFF6FF`): `Perimeter 1 — Identity & Access Federation` (4 large icon cards)
      - Gate 2 (Column 2, Teal `#F0FDFA`): `Perimeter 2 — Network & Zero-Trust Edge` (4 large icon cards)
      - Central Zero-Trust Application & AI Enclave (Split Top/Bottom):
        - Top (`Perimeter 3 — App RBAC, State-Guard & Separation of Duties`, Amber `#FEF3C7`): 2x2 grid of RBAC/State/SoD cards
        - Bottom (`Perimeter 4 — AI Trust Layer & Zero-Leak Data Privacy`, Purple `#F3E8FF`): 2x2 grid of AI/Privacy cards
      - Gate 5 (Right Vault Column, Rose `#FCE8E6`): `Perimeter 5 — KMS Encryption, Secrets & SIEM Vault` (4 large vault cards)
    - Bottom Full-Width Bar: `Zero-Trust Policy Rejection & Continuous Compliance Enforcement Loop` (`401` / `403` / `409` / `SIEM Audit`)
    """
    title = str(parsed.get("title") or "Zero-Trust & AI Security Architecture").strip()
    root_sgs = parsed.get("rootSubgraphs") or []
    if len(root_sgs) == 1 and len(root_sgs[0].get("children") or []) >= 3:
        layers = root_sgs[0]["children"]
    else:
        layers = root_sgs

    def _layer_cards(idx: int) -> list[dict[str, Any]]:
        if idx >= len(layers):
            return []
        l_sg = layers[idx]
        out = list(l_sg.get("cards") or [])
        for ch in l_sg.get("children") or []:
            out.extend(ch.get("cards") or [])
        return out[:4]

    l1_cards = _layer_cards(0)
    l2_cards = _layer_cards(1)
    l3_cards = _layer_cards(2)
    l4_cards = _layer_cards(3)
    l5_cards = _layer_cards(4)

    svg: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 860" width="1440" height="860" '
        'font-family="\'Google Sans\', \'Roboto\', \'Inter\', -apple-system, BlinkMacSystemFont, \'Segoe UI\', Arial, sans-serif">',
        "<defs>",
        '  <marker id="secArrGreen" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#0D9488"/>',
        "  </marker>",
        '  <marker id="secArrRed" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">',
        '    <path d="M 1 1.5 L 8.5 5 L 1 8.5 Z" fill="#D93025"/>',
        "  </marker>",
        "</defs>",
        '<rect x="0" y="0" width="1440" height="860" fill="#FFFFFF"/>',
        f'<text x="44" y="54" font-size="28" font-weight="700" fill="#202124">{_esc(title)}</text>',
        '<text x="44" y="78" font-size="13.5" font-weight="500" fill="#5F6368">Zero-Trust Defense-in-Depth Inspection Pipeline: Gate 1 (Identity/MFA) → Gate 2 (WAF/mTLS) → Gate 3 &amp; 4 (RBAC/State &amp; AI Trust Enclave) → Gate 5 (KMS Vault)</text>',
    ]

    top_y = 104.0
    col_h = 584.0

    # --- GATE 1: Identity & Access Federation (x=44, w=276) ---
    g1_x, g1_w = 44.0, 276.0
    svg.append(
        f'<rect x="{g1_x:.1f}" y="{top_y:.1f}" width="{g1_w:.1f}" height="{col_h:.1f}" rx="14" '
        f'fill="#EFF6FF" stroke="#1D4ED8" stroke-width="2.2"/>'
        f'<rect x="{g1_x + 16:.1f}" y="{top_y + 12:.1f}" width="{g1_w - 32:.1f}" height="28.0" rx="8" fill="#1D4ED8"/>'
        f'<text x="{g1_x + g1_w / 2.0:.1f}" y="{top_y + 30.5:.1f}" text-anchor="middle" font-size="12.8" font-weight="700" fill="#FFFFFF">'
        f'Gate 1 — Identity &amp; Federation</text>'
    )
    l1_icons = ["persona", "security", "rules", "security"]
    for i, c in enumerate(l1_cards):
        cy = top_y + 54.0 + i * 128.0
        svg.append(
            _draw_modern_icon_card(
                g1_x + 14.0,
                cy,
                g1_w - 28.0,
                106.0,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=l1_icons[i % len(l1_icons)],
                stroke="#1D4ED8",
                badge_bg="#DBEAFE",
                step_num=i + 1,
            )
        )

    # Verified Arrow Gate 1 -> Gate 2
    svg.append(
        f'<line x1="{g1_x + g1_w + 2:.1f}" y1="{top_y + col_h / 2.0:.1f}" x2="350.0" y2="{top_y + col_h / 2.0:.1f}" '
        f'stroke="#0D9488" stroke-width="2.8" marker-end="url(#secArrGreen)"/>'
    )

    # --- GATE 2: Network & Zero-Trust Edge (x=354, w=276) ---
    g2_x, g2_w = 354.0, 276.0
    svg.append(
        f'<rect x="{g2_x:.1f}" y="{top_y:.1f}" width="{g2_w:.1f}" height="{col_h:.1f}" rx="14" '
        f'fill="#F0FDFA" stroke="#0D9488" stroke-width="2.2"/>'
        f'<rect x="{g2_x + 16:.1f}" y="{top_y + 12:.1f}" width="{g2_w - 32:.1f}" height="28.0" rx="8" fill="#0D9488"/>'
        f'<text x="{g2_x + g2_w / 2.0:.1f}" y="{top_y + 30.5:.1f}" text-anchor="middle" font-size="12.8" font-weight="700" fill="#FFFFFF">'
        f'Gate 2 — WAF, TLS 1.3 &amp; mTLS</text>'
    )
    l2_icons = ["security", "network", "security", "network"]
    for i, c in enumerate(l2_cards):
        cy = top_y + 54.0 + i * 128.0
        svg.append(
            _draw_modern_icon_card(
                g2_x + 14.0,
                cy,
                g2_w - 28.0,
                106.0,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=l2_icons[i % len(l2_icons)],
                stroke="#0D9488",
                badge_bg="#CCFBF1",
            )
        )

    # Verified Arrows Gate 2 -> Enclave Top & Bottom
    svg.append(
        f'<line x1="{g2_x + g2_w + 2:.1f}" y1="{top_y + 142.0:.1f}" x2="660.0" y2="{top_y + 142.0:.1f}" '
        f'stroke="#0D9488" stroke-width="2.8" marker-end="url(#secArrGreen)"/>'
    )
    svg.append(
        f'<line x1="{g2_x + g2_w + 2:.1f}" y1="{top_y + 442.0:.1f}" x2="660.0" y2="{top_y + 442.0:.1f}" '
        f'stroke="#0D9488" stroke-width="2.8" marker-end="url(#secArrGreen)"/>'
    )

    # --- CENTRAL ZERO-TRUST APPLICATION & AI ENCLAVE (x=664, w=420) ---
    g3_x, g3_w = 664.0, 420.0
    enc_h = 280.0
    cell_w = (g3_w - 40.0) / 2.0
    cell_h = 98.0

    # Top Enclave: Gate 3 — Application RBAC, State-Guard & Separation of Duties (y=104, h=280)
    svg.append(
        f'<rect x="{g3_x:.1f}" y="{top_y:.1f}" width="{g3_w:.1f}" height="{enc_h:.1f}" rx="14" '
        f'fill="#FFFBEB" stroke="#D97706" stroke-width="2.4"/>'
        f'<rect x="{g3_x + 16:.1f}" y="{top_y + 12:.1f}" width="{g3_w - 32:.1f}" height="28.0" rx="8" fill="#D97706"/>'
        f'<text x="{g3_x + g3_w / 2.0:.1f}" y="{top_y + 30.5:.1f}" text-anchor="middle" font-size="12.8" font-weight="700" fill="#FFFFFF">'
        f'Gate 3 — Application RBAC, State &amp; SoD Guards</text>'
    )
    l3_icons = ["security", "workflow", "security", "rules"]
    for i, c in enumerate(l3_cards[:4]):
        row = i // 2
        col = i % 2
        cx = g3_x + 14.0 + col * (cell_w + 12.0)
        cy = top_y + 52.0 + row * (cell_h + 14.0)
        svg.append(
            _draw_modern_icon_card(
                cx,
                cy,
                cell_w,
                cell_h,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=l3_icons[i % len(l3_icons)],
                stroke="#D97706",
                badge_bg="#FEF3C7",
            )
        )

    # Bottom Enclave: Gate 4 — AI Trust Layer & Zero-Leak Data Privacy (y=408, h=280)
    g4_y = top_y + enc_h + 24.0
    svg.append(
        f'<rect x="{g3_x:.1f}" y="{g4_y:.1f}" width="{g3_w:.1f}" height="{enc_h:.1f}" rx="14" '
        f'fill="#F5F3FF" stroke="#7E22CE" stroke-width="2.4"/>'
        f'<rect x="{g3_x + 16:.1f}" y="{g4_y + 12:.1f}" width="{g3_w - 32:.1f}" height="28.0" rx="8" fill="#7E22CE"/>'
        f'<text x="{g3_x + g3_w / 2.0:.1f}" y="{g4_y + 30.5:.1f}" text-anchor="middle" font-size="12.8" font-weight="700" fill="#FFFFFF">'
        f'Gate 4 — AI Trust Layer &amp; Zero-Leak Privacy</text>'
    )
    l4_icons = ["security", "security", "ai", "persona"]
    for i, c in enumerate(l4_cards[:4]):
        row = i // 2
        col = i % 2
        cx = g3_x + 14.0 + col * (cell_w + 12.0)
        cy = g4_y + 52.0 + row * (cell_h + 14.0)
        svg.append(
            _draw_modern_icon_card(
                cx,
                cy,
                cell_w,
                cell_h,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=l4_icons[i % len(l4_icons)],
                stroke="#7E22CE",
                badge_bg="#F3E8FF",
            )
        )

    # Arrows from Gate 3 & 4 -> Gate 5 (Vault)
    svg.append(
        f'<line x1="{g3_x + g3_w + 2:.1f}" y1="{top_y + 142.0:.1f}" x2="1114.0" y2="{top_y + 142.0:.1f}" '
        f'stroke="#D93025" stroke-width="2.8" marker-end="url(#secArrRed)"/>'
    )
    svg.append(
        f'<line x1="{g3_x + g3_w + 2:.1f}" y1="{g4_y + 142.0:.1f}" x2="1114.0" y2="{g4_y + 142.0:.1f}" '
        f'stroke="#D93025" stroke-width="2.8" marker-end="url(#secArrRed)"/>'
    )

    # --- GATE 5: KMS Encryption, Secrets & SIEM Vault (x=1118, w=278) ---
    g5_x, g5_w = 1118.0, 278.0
    svg.append(
        f'<rect x="{g5_x:.1f}" y="{top_y:.1f}" width="{g5_w:.1f}" height="{col_h:.1f}" rx="14" '
        f'fill="#FCE8E6" stroke="#D93025" stroke-width="2.4"/>'
        f'<rect x="{g5_x + 16:.1f}" y="{top_y + 12:.1f}" width="{g5_w - 32:.1f}" height="28.0" rx="8" fill="#D93025"/>'
        f'<text x="{g5_x + g5_w / 2.0:.1f}" y="{top_y + 30.5:.1f}" text-anchor="middle" font-size="12.8" font-weight="700" fill="#FFFFFF">'
        f'Gate 5 — KMS, Secrets &amp; SIEM Vault</text>'
    )
    l5_icons = ["security", "storage", "rules", "observability"]
    for i, c in enumerate(l5_cards):
        cy = top_y + 54.0 + i * 128.0
        svg.append(
            _draw_modern_icon_card(
                g5_x + 14.0,
                cy,
                g5_w - 28.0,
                106.0,
                c.get("line1", ""),
                c.get("line2", ""),
                icon_kind=l5_icons[i % len(l5_icons)],
                stroke="#D93025",
                badge_bg="#FEE2E2",
            )
        )

    # --- BOTTOM BAR: Zero-Trust Policy Rejection & Threat Telemetry Bar (y=708, h=120) ---
    rej_y, rej_h = 708.0, 120.0
    total_w = 1352.0
    svg.append(
        f'<rect x="44.0" y="{rej_y:.1f}" width="{total_w:.1f}" height="{rej_h:.1f}" rx="14" '
        f'fill="#FEF2F2" stroke="#B91C1C" stroke-width="2.0" stroke-dasharray="6,4"/>'
        f'<text x="64.0" y="{rej_y + 25:.1f}" font-size="13.8" font-weight="700" fill="#991B1B">'
        f'Zero-Trust Policy Rejection &amp; Continuous Threat Telemetry (Fail-Closed Enforcement Across All Gates)</text>'
    )
    rej_items = [
        ("401 Unauthenticated", "Missing / Expired OIDC JWT", "security"),
        ("403 Forbidden (RBAC / SoD)", "Unauthorized Role or Self-Approval", "security"),
        ("409 / 422 Policy Rejected", "Illegal State Transition or Rule Breach", "workflow"),
        ("Zero-Leak & SIEM Audit", "PII Redacted · All Rejections Logged", "observability"),
    ]
    rw = (total_w - 40.0 - 3 * 16.0) / 4.0
    for i, (r1, r2, ric) in enumerate(rej_items):
        rx = 64.0 + i * (rw + 16.0)
        svg.append(
            _draw_modern_icon_card(
                rx,
                rej_y + 36.0,
                rw,
                70.0,
                r1,
                r2,
                icon_kind=ric,
                stroke="#B91C1C",
                badge_bg="#FEE2E2",
            )
        )

    svg.append("</svg>")
    return "\n".join(svg) + "\n"


def write_security_architecture_svg_and_png(parsed: dict[str, Any], svg_path: Path) -> tuple[Path, Path | None]:
    return _save_svg_and_png(render_security_architecture_svg(parsed), svg_path, width=1440, height=860)



