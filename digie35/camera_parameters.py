"""Translation of portable profile values; never invent a camera choice."""
import math
import re


def logical_value(mapping, value):
    for logical, concrete in mapping.get('values', {}).items():
        aliases = concrete if isinstance(concrete, list) else [concrete]
        if any(str(alias).casefold() == str(value).casefold() for alias in aliases):
            return str(logical)
    fmt = mapping.get('number_format', '')
    if fmt.count('%f') == 1:
        try:
            return fmt.replace('%f', format(float(value), 'g'))
        except (ValueError, TypeError):
            pass
    return value


def seconds(value):
    match = re.fullmatch(r'(\d+(?:\.\d+)?)(?:/(\d+(?:\.\d+)?))?\s*s?', str(value).strip(), re.I)
    if not match:
        return None
    denominator = float(match[2] or 1)
    result = float(match[1]) / denominator if denominator else 0
    return result if math.isfinite(result) and result > 0 else None


def camera_value(mapping, value, item):
    mapped = mapping.get('values', {}).get(str(value), value)
    if isinstance(mapped, list):
        for alias in mapped:
            for choice in item.get('choices', []):
                if str(choice).casefold() == str(alias).casefold():
                    return choice
        raise ValueError(f'No camera choice matches aliases for {value!r}')
    fmt = mapping.get('number_format', '')
    if mapped == value and fmt.count('%f') == 1:
        prefix, suffix = fmt.split('%f')
        text = str(value).strip()
        if text.startswith(prefix) and text.endswith(suffix):
            number = text[len(prefix):len(text)-len(suffix) if suffix else None]
            try:
                mapped = format(float(number), 'g')
            except ValueError:
                pass
    choices = item.get('choices', [])
    for choice in choices:
        if str(choice).casefold() == str(mapped).casefold():
            return choice
    if fmt or item.get('id', '').rsplit('/', 1)[-1] == 'exposurecompensation':
        for choice in choices:
            try:
                if math.isfinite(float(mapped)) and float(choice) == float(mapped):
                    return choice
            except (ValueError, TypeError):
                pass
    if mapping.get('value_type') == 'shutter_speed':
        target = seconds(mapped)
        candidates = []
        for choice in choices:
            duration = seconds(choice)
            decimal = re.fullmatch(r'\d+\.(\d+)\s*s?', str(choice), re.I)
            rounding = .5 * 10 ** -len(decimal[1]) if decimal else 0
            if target and duration and abs(duration-target) <= max(rounding, target*.005) + 1e-12:
                candidates.append((abs(duration-target), choice))
        if candidates:
            return min(candidates, key=lambda candidate: candidate[0])[1]
    if choices:
        raise ValueError(f'No camera choice matches {value!r}')
    if item.get('type_name') == 'range':
        number = float(mapped)
        bounds = item['range']
        if not math.isfinite(number) or not bounds['minimum'] <= number <= bounds['maximum']:
            raise ValueError(f'Value {value!r} is outside the camera range')
        increment = bounds.get('increment', 0)
        if increment and not math.isclose((number-bounds['minimum']) / increment, round((number-bounds['minimum']) / increment), abs_tol=1e-6):
            raise ValueError(f'Value {value!r} does not match the camera increment')
        return number
    return mapped


def logical_catalog(matches):
    result = []
    for definition in matches['parameters']:
        raw = definition.get('camera_parameter')
        if not raw or raw.get('error'):
            continue
        mapping = definition.get('mapping') or {}
        item = dict(raw, id=definition['id'], occurrence=0, kind='logical', label=definition['label'])
        item['value'] = logical_value(mapping, raw.get('value'))
        if 'choices' in raw:
            item['choices'] = list(dict.fromkeys(logical_value(mapping, choice) for choice in raw['choices']))
        result.append(item)
    return result
