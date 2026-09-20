"""A-Bogus signature algorithm for Douyin Web, pure Python implementation."""

from random import Random
from time import time

from .sm3 import sm3_to_array

__all__ = [
    "ABogus",
    "DEFAULT_BROWSER_INFO",
]

# a_bogus alphabets
ALPHABETS: dict[str, str] = {
    "s3": "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe",
    "s4": "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe",
}

SALT = "dhzx"
HEADER_MAGIC: tuple[int, int] = (3, 82)
SDK_VERSION: tuple[int, int, int, int] = (1, 0, 1, 0)
PAYLOAD_KEY = 0xD3
FORTNIGHT_EPOCH_MS = 1_721_836_800_000
PAGE_ID = 6241
AID = 6383

NOISE_MASKS: tuple[int, int, int] = (0x91, 0x42, 0x2C)
DATA_MASKS: tuple[int, int, int] = (0x6E, 0xBD, 0xD3)

FIELD_ORDER: tuple[str, ...] = (
    "L34", "L44", "L56", "L61", "L73", "L29", "L70", "L45", "L35", "L49",
    "L38", "L66", "L51", "L68", "L28", "L48", "L64", "L47", "L30", "L71",
    "L26", "L55", "L31", "L69", "L59", "L40", "L62", "L63", "L27", "L72",
    "L41", "L74", "L57", "L52", "L42", "L39", "L33", "L67", "L53", "L43",
    "L65", "L46", "L36", "L24", "L60", "L32", "L79", "L80", "L84", "L85",
)

CANARIES: tuple[tuple[int, int, int], ...] = ((3, 11, 12), (4, 8, 9), (5, 12, 13))


class DigestChain:
    __slots__ = ("slots", "indices", "canary")

    def __init__(
        self,
        slots: tuple[str, str, str],
        indices: tuple[int, int],
        canary: tuple[int, int, int],
    ):
        self.slots = slots
        self.indices = indices
        self.canary = canary


DIGEST_CHAINS: dict[str, DigestChain] = {
    "query": DigestChain(("L48", "L49", "L51"), (9, 18), CANARIES[0]),
    "body": DigestChain(("L52", "L53", "L55"), (10, 19), CANARIES[1]),
    "user_agent": DigestChain(("L56", "L57", "L59"), (11, 21), CANARIES[2]),
}

ENV_FLAGS = 1
DETECT_FLAGS = 14
NR_FLAGS = 0x21
NR_TAG: tuple[int, int, int, int] = (0, 0, 0, 0)
TRIPWIRE_LOCKED = 3
CALL_BUCKET = 6
DEFAULT_BROWSER_INFO = "1536|742|1536|864|1536|864|1536|864|MacIntel"

_HEADER_NOISE_BANDS: dict[str, int] = {
    "chrome": 0,
    "firefox": 40,
    "safari": 81,
    "edge": 125,
    "huawei": 170,
    "other": 210,
}

_TRIPWIRE_SET = 0xB2
_TRIPWIRE_FREE = 0x4D


def _family_of(user_agent: str) -> str:
    ua = user_agent.lower()
    for name in ("edg", "huawei", "firefox", "chrome", "safari"):
        if name in ua:
            return {"edg": "edge"}.get(name, name)
    return "other"


def _header_noise(user_agent: str, rng: Random) -> int:
    base = _HEADER_NOISE_BANDS.get(_family_of(user_agent), _HEADER_NOISE_BANDS["other"])
    return (base + int(rng.random() * 40)) & 0xFF


def _probe_noise(rng: Random) -> int:
    value = int(rng.random() * 240)
    return value + value % 2 + 1 if value > 109 else value


def _tripwire_noise(rng: Random) -> int:
    return (int(rng.random() * 255) & _TRIPWIRE_FREE) | _TRIPWIRE_SET


def _mask_pair(
    pair: tuple[int, int],
    rng: Random,
    *,
    low: int | None = None,
    high: int | None = None,
) -> list[int]:
    noise = int(rng.random() * 65535)
    low = noise & 0xFF if low is None else low & 0xFF
    high = (noise >> 8) & 0xFF if high is None else high & 0xFF
    return [
        (low & 0xAA) | (pair[0] & 0x55),
        (low & 0x55) | (pair[0] & 0xAA),
        (high & 0xAA) | (pair[1] & 0x55),
        (high & 0x55) | (pair[1] & 0xAA),
    ]


def _expand_noise(body: bytes, rng: Random) -> bytes:
    out = bytearray()
    for offset in range(0, len(body), 3):
        group = body[offset : offset + 3]
        if len(group) < 3:
            out.append(group[0])
            if len(group) > 1 and group[1]:
                out.append(group[1])
            continue
        noise = int(rng.random() * 1000) & 0xFF
        out.extend(
            (noise & mask) | (byte & data)
            for mask, data, byte in zip(NOISE_MASKS, DATA_MASKS, group, strict=True)
        )
        out.append(
            (group[0] & NOISE_MASKS[0])
            | (group[1] & NOISE_MASKS[1])
            | (group[2] & NOISE_MASKS[2])
        )
    return bytes(out)


def js_bytes(text: str) -> bytes:
    out = bytearray()
    units = text.encode("utf-16-le")
    for index in range(0, len(units), 2):
        code = units[index] | (units[index + 1] << 8)
        if code & 0xFF00:
            out.append(code >> 8)
        out.append(code & 0xFF)
    return bytes(out)


def _le_bytes(value: int, count: int) -> list[int]:
    return [(value >> (8 * index)) & 0xFF for index in range(count)]


def canary(digest: list[int], offset: int, sentinel: int, fallback: int) -> int:
    for byte in digest[offset:]:
        if byte != sentinel:
            return byte
    return fallback


def digest_of(text: str) -> list[int]:
    return sm3_to_array(sm3_to_array(text + SALT))


def user_agent_digest(user_agent: str) -> list[int]:
    key = bytes((ENV_FLAGS // 256, ENV_FLAGS % 256, DETECT_FLAGS % 256))
    sealed = rc4(key, bytes(byte & 0xFF for byte in js_bytes(user_agent.strip())))
    return sm3_to_array(encode_base64(sealed, "s3"))


def chain_bytes(chain: DigestChain, digest: list[int]) -> tuple[int, int, int]:
    first, second = chain.indices
    return digest[first], digest[second], canary(digest, *chain.canary)


def rc4(key: bytes, data: bytes) -> bytes:
    box = [0] * 256
    for i in range(256):
        box[255 - i] = i
    j = 0
    for i in range(256):
        j = (j * box[i] + j + key[i % len(key)]) % 256
        box[i], box[j] = box[j], box[i]

    out = bytearray(len(data))
    i = j = 0
    for index, byte in enumerate(data):
        i = (i + 1) % 256
        j = (j + box[i]) % 256
        box[i], box[j] = box[j], box[i]
        out[index] = byte ^ box[(box[i] + box[j]) % 256]
    return bytes(out)


def encode_base64(data: bytes, alphabet: str = "s4") -> str:
    table = ALPHABETS[alphabet]
    out: list[str] = []
    for offset in range(0, len(data), 3):
        chunk = data[offset : offset + 3]
        block = int.from_bytes(chunk + b"\x00" * (3 - len(chunk)), "big")
        digits = [(block >> shift) & 0x3F for shift in (18, 12, 6, 0)]
        out.extend(table[digit] for digit in digits[: len(chunk) + 1])
    out.append("=" * ((4 - len(out) % 4) % 4))
    return "".join(out)


class ABogus:
    def __init__(
        self,
        user_agent: str,
        *,
        browser_info: str = DEFAULT_BROWSER_INFO,
        page_id: int = PAGE_ID,
        aid: int = AID,
        rng: Random | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.browser_info = browser_info
        self.page_id = page_id
        self.aid = aid
        self._rng = rng or Random()

    def _fields(self, query: str, body: str, now_ms: int) -> dict[str, int]:
        digests = {
            "query": digest_of(query),
            "body": digest_of(body),
            "user_agent": user_agent_digest(self.user_agent),
        }

        ink = now_ms - 1
        fortnights = (now_ms - FORTNIGHT_EPOCH_MS) // (1000 * 60 * 60 * 24 * 14)
        info_bytes = js_bytes(self.browser_info)
        tail_bytes = js_bytes(f"{(now_ms + 3) & 0xFF},")

        fields: dict[str, int] = {
            "L24": 41,
            "L26": fortnights,
            "L27": CALL_BUCKET,
            "L28": 3,
            "L35": ENV_FLAGS & 0xFF,
            "L36": (ENV_FLAGS // 256) & 0xFF,
            "L38": NR_FLAGS & 0xFF,
            "L39": (NR_FLAGS >> 8) & 0xFF,
            "L66": TRIPWIRE_LOCKED,
            "L79": len(info_bytes) & 0xFF,
            "L80": (len(info_bytes) >> 8) & 0xFF,
            "L84": len(tail_bytes) & 0xFF,
            "L85": (len(tail_bytes) >> 8) & 0xFF,
        }
        for index, byte in enumerate(_le_bytes(now_ms, 6)):
            fields[f"L{29 + index}"] = byte
        for index, byte in enumerate(_le_bytes(DETECT_FLAGS, 4)):
            fields[f"L{44 + index}"] = byte
        for index, byte in enumerate(NR_TAG):
            fields[f"L{40 + index}"] = byte
        for index, byte in enumerate(_le_bytes(ink, 6)):
            fields[f"L{60 + index}"] = byte
        for index, byte in enumerate(_le_bytes(self.page_id, 4)):
            fields[f"L{67 + index}"] = byte
        for index, byte in enumerate(_le_bytes(self.aid, 4)):
            fields[f"L{71 + index}"] = byte
        for name, chain in DIGEST_CHAINS.items():
            written = chain_bytes(chain, digests[name])
            for slot, value in zip(chain.slots, written, strict=True):
                fields[slot] = value
        return fields

    def get_value(
        self,
        query: str,
        *,
        body: str = "",
        content_type: str = "",
        now_ms: int | None = None,
    ) -> str:
        if "multipart/form-data" in content_type.lower():
            body = ""
        now = now_ms if now_ms is not None else int(time() * 1000)
        if now < FORTNIGHT_EPOCH_MS:
            raise ValueError(f"clock is before the a_bogus epoch: {now}")
        fields = self._fields(query, body, now)

        version = _mask_pair(SDK_VERSION[:2], self._rng) + _mask_pair(
            SDK_VERSION[2:],
            self._rng,
            low=_probe_noise(self._rng),
            high=_tripwire_noise(self._rng),
        )

        checksum = 0
        for byte in version:
            checksum ^= byte
        for name in FIELD_ORDER:
            checksum ^= fields[name]

        body_bytes = bytes(fields[name] for name in FIELD_ORDER)
        body_bytes += js_bytes(self.browser_info)
        body_bytes += js_bytes(f"{(now + 3) & 0xFF},")
        body_bytes += bytes((checksum,))

        header = bytes(
            _mask_pair(
                HEADER_MAGIC, self._rng, high=_header_noise(self.user_agent, self._rng)
            )
        )
        frame = _expand_noise(body_bytes, self._rng)
        sealed = rc4(bytes((PAYLOAD_KEY,)), bytes(version) + frame)
        return encode_base64(header + sealed, "s4")
