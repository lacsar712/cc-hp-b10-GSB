import re

# 货位码格式：汉字仓名 + “/” + 两位货架号，例如「甲仓/01」。
# 仓名至少一个汉字（可夹汉字），斜线为半角或全角，货架号固定两位数字。
_LOCATION_RE = re.compile(r"^(?P<warehouse>[一-鿿]+)[/／](?P<shelf>\d{2})$")


def judge(doc: dict) -> tuple[str, str]:
    steps = doc.get("steps") or []
    fry = next((s for s in steps if s.get("name") == "清炒"), None)
    if fry is None:
        return "未放行", "缺少清炒工序"
    temp = float(fry.get("temp_c", 0))
    minutes = float(fry.get("minutes", 0))
    if not 80 <= temp <= 150:
        return "未放行", "清炒温度不在范围内"
    if not 5 <= minutes <= 30:
        return "未放行", "清炒时长不在范围内"
    return "放行", "清炒工序符合炮制要求"


def validate_warehouse(name: str) -> str:
    """炮制员设定的仓名：纯汉字、非空，去掉首尾空白。"""
    name = (name or "").strip()
    if not name or not re.fullmatch(r"[一-鿿]+", name):
        raise ValueError("仓名须为汉字，例如：甲仓")
    return name


def normalize_location(code: str) -> str:
    """规范化货位码（去空白、全角斜线转半角），不合法抛 ValueError。"""
    code = (code or "").strip()
    m = _LOCATION_RE.fullmatch(code)
    if not m:
        raise ValueError("货位码须为：汉字仓名/两位货架号，例如 甲仓/01")
    return f"{m.group('warehouse')}/{m.group('shelf')}"
