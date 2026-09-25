import re

# 仓名须为汉字（如「甲仓」），货架号为固定位数的数字，中间以斜线相连。
WAREHOUSE_RE = re.compile(r"^[一-鿿]{1,12}$")


def valid_warehouse(name: str) -> bool:
    return bool(WAREHOUSE_RE.fullmatch(name.strip()))


def location_pattern(rule: dict) -> re.Pattern:
    """把当前规则编译成整体匹配的正则：仓名/货架号。"""
    warehouse = re.escape(rule["warehouse_name"].strip())
    digits = int(rule["shelf_digits"])
    return re.compile(rf"^{warehouse}/\d{{{digits}}}$")


def valid_location(code: str, rule: dict) -> bool:
    return bool(location_pattern(rule).fullmatch(code.strip()))


def location_hint(rule: dict) -> str:
    """给出当前规则下的示例货位码，如 甲仓/01。"""
    example = "0" * (int(rule["shelf_digits"]) - 1) + "1"
    return f'{rule["warehouse_name"].strip()}/{example}'


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
