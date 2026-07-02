"""Shared render helpers used by both the Stocks and Mutual-Funds pages so the
tables, badges, stat tiles, check-grids and manual-review panels look identical.
"""

from __future__ import annotations

import streamlit as st

from components.theme import (VERDICT_STYLE, QUALITY_COLOR, STATUS_COLOR,
                              MUTED, GOOD, WARNING, CRITICAL, INK, BORDER)


# ---------- formatting ----------
def fmt_pct(x, nd=1, sign=True):
    if not isinstance(x, (int, float)):
        return "—"
    return f"{x:+.{nd}f}%" if sign else f"{x:.{nd}f}%"


def fmt_num(x, p="", s="", nd=1):
    return f"{p}{x:,.{nd}f}{s}" if isinstance(x, (int, float)) else "—"


# ---------- badges ----------
def badge_html(verdict: str) -> str:
    color, icon = VERDICT_STYLE.get(verdict, (MUTED, "•"))
    return (f'<span class="badge" style="color:{color};background:{color}22;'
            f'border-color:{color}55;">{icon} {verdict}</span>')


# ---------- stat tiles ----------
def stat_tile(col, label, value, color=INK):
    col.markdown(f'<div class="tile"><div class="k">{label}</div>'
                 f'<div class="v" style="color:{color}">{value}</div></div>',
                 unsafe_allow_html=True)


# ---------- dataframe stylers ----------
def style_verdict(val):
    color, _ = VERDICT_STYLE.get(val, (MUTED, ""))
    return f"color:{color}; font-weight:700;"


def style_quality(val):
    return f"color:{QUALITY_COLOR.get(val, MUTED)}; font-weight:700;"


# ---------- check-grid row (used for MF C-grid & fundamental quality) ----------
def check_row(label, value, status, note="", cid=None):
    """One PASS/CAUTION/FAIL row with a status chip."""
    color = STATUS_COLOR.get(status, MUTED)
    id_html = f'<div class="crit-id">{cid}</div>' if cid else ""
    note_html = f'<div class="crit-det">{note}</div>' if note else ""
    val_html = (f'<div class="crit-lab" style="min-width:6rem;text-align:right;">{value}</div>'
                if value not in (None, "") else "")
    st.markdown(
        f'<div class="crit-row">{id_html}'
        f'<div style="flex:1;"><div class="crit-lab">{label}</div>{note_html}</div>'
        f'{val_html}'
        f'<div class="crit-st" style="color:{color};background:{color}22;margin-left:.7rem;">{status}</div>'
        f'</div>', unsafe_allow_html=True)


# ---------- manual-review row (shared across sections) ----------
_SEV_COLOR = {"high": CRITICAL, "medium": WARNING, "info": MUTED}
_SEV_LABEL = {"high": "MUST CHECK", "medium": "CHECK", "info": "NOTE"}


def manual_row(title, detail, where, sev="medium"):
    color = _SEV_COLOR.get(sev, MUTED)
    st.markdown(
        f'<div class="crit-row" style="border-left:3px solid {color};">'
        f'<div style="flex:1;"><div class="crit-lab">{title}</div>'
        f'<div class="crit-det">{detail}</div>'
        f'<div class="crit-det" style="color:{color};">🔎 Check on: {where}</div></div>'
        f'<div class="crit-st" style="color:{color};background:{color}22;white-space:nowrap;">'
        f'{_SEV_LABEL.get(sev, "CHECK")}</div>'
        f'</div>', unsafe_allow_html=True)


def render_verify_panel(results, item="ticker"):
    """Show a pre-flight verification result: valid vs not-found, each in a
    copyable code block (st.code has a built-in 📋 copy button)."""
    valid = [r for r in results if r.get("valid")]
    invalid = [r for r in results if not r.get("valid")]
    n_ok, n_bad = len(valid), len(invalid)

    if n_bad == 0:
        st.success(f"✅ All {n_ok} {item}s are valid — go ahead and hit **Run analysis**.")
    else:
        st.warning(f"⚠️ {n_bad} of {n_ok + n_bad} {item}s couldn't be found. Copy the ❌ list, "
                   f"fix it (e.g. paste into an LLM: *“correct these to valid NSE {item}s”*), "
                   f"paste back into the box, and re-verify.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**❌ Not found ({n_bad})**")
        if invalid:
            st.caption("Copy (📋 top-right of the box) → give to an LLM to fix:")
            st.code("\n".join(r["name"] for r in invalid), language=None)
            with st.expander("Why each failed"):
                for r in invalid:
                    st.markdown(f"- **{r['name']}** — {r.get('reason') or 'not found'}")
        else:
            st.caption("None 🎉")
    with c2:
        st.markdown(f"**✅ Valid ({n_ok})**")
        if valid:
            st.caption("Resolved to:")
            st.code("\n".join(f"{r['name']}  →  {r.get('symbol') or ''}".strip(" →")
                              for r in valid), language=None)
        else:
            st.caption("None yet")


def group_label(text):
    st.markdown(f'<div style="color:{MUTED};font-size:.72rem;text-transform:uppercase;'
                f'letter-spacing:.07em;margin:.6rem 0 .25rem;">{text}</div>',
                unsafe_allow_html=True)
