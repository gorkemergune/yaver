"""A question the team asked and is waiting on, kept on the conversation (pending_action).

Live runs: Friday answered "Geçen salı EE211'e gitmedim" with "18 Kasım Çarşamba mı?", and
the user's "Evet, çarşamba" sometimes recorded nothing: the coordinator delegated the bare
words and the yaver, who sees only its instruction, had nothing to attach them to.

Now the code remembers what is open:
- from a tool result: `log_attendance` suggesting another day, a tool listing `candidates`
  (two matching blocks / courses / tasks...), or a proposal table shown this turn. Each
  option is the tool call that finishes the job.
- from a yaver's reply that ends in a question (no options): who asked, what about.

A short answer ("evet", "çarşamba", "2.si", "lab olan") is matched to an option in code and
that tool call runs; otherwise it goes back to the yaver who asked, with its question.
"""

import datetime as dt
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.time_resolver import MONTH_NAMES_TR, WEEKDAY_NAMES_TR, normalize


def word_set(words: str) -> frozenset[str]:
    return frozenset(words.split())


# An answer to a question is short; anything longer is a new message for the coordinator.
MAX_REPLY_WORDS = 8
# An unanswered question does not wait forever.
MAX_AGE = dt.timedelta(hours=24)  # a Sunday-evening draft answered in the morning

YES = word_set(
    "evet olur tamam aynen dogru ok okey tabii tabi uygun onayliyorum onay peki he hi "
    "yap kaydet isle ekle uygula olsun lutfen yaz hepsi hepsini"
)
NO = word_set("hayir yok vazgec bosver istemiyorum gerek yapma")
# Words that carry no choice: "o gün", "13'te", "lab olan", "onu".
FILLER = word_set(
    "o onu bu su gun gunu gunku saat saatte olan olani te ta de da ki si su i u a e ye ya "
    "deki daki ile icin ama sey diyorum demek istedim kastettim yani hani"
)
ORDINAL_WORDS = {
    "ilk": 1,
    "ilki": 1,
    "ilkini": 1,
    "birinci": 1,
    "birincisi": 1,
    "ikinci": 2,
    "ikincisi": 2,
    "ikinciyi": 2,
    "ucuncu": 3,
    "ucuncusu": 3,
    "dorduncu": 4,
    "dorduncusu": 4,
}
LAST_WORDS = frozenset({"son", "sonuncu", "sonuncusu", "sonuncuyu", "sondaki"})


@dataclass(slots=True)
class Option:
    label: str  # shown to the model ("2026-11-18 Çarşamba")
    value: Any  # goes into the tool call's `slot`
    keys: list[str]  # normalized words that pick this option ("carsamba", "18", "kasim")


@dataclass(slots=True)
class PendingAction:
    agent_id: str  # who asked
    request: str  # what that yaver was asked to do (its instruction / the user's message)
    question: str = ""  # its reply with the question (filled at the end of the turn)
    tool: str | None = None  # the call that finishes the job, None = only a question
    arguments: dict[str, Any] = field(default_factory=dict)
    slot: str | None = None  # the argument an option fills
    drop: list[str] = field(default_factory=list)  # arguments replaced by the slot
    options: list[Option] = field(default_factory=list)
    created_at: str = ""  # ISO, UTC

    def dump(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def load(cls, data: dict[str, Any] | None) -> "PendingAction | None":
        if not data:
            return None
        try:
            options = [Option(**o) for o in data.get("options") or []]
            return cls(**{**data, "options": options})
        except TypeError:  # an older shape: forget it rather than fail the message
            return None

    def expired(self, now: dt.datetime) -> bool:
        try:
            created = dt.datetime.fromisoformat(self.created_at)
        except ValueError:
            return True
        return now - created > MAX_AGE

    def call(self, option: Option) -> tuple[str, dict[str, Any]]:
        if self.tool is None or self.slot is None:
            raise ValueError("a question without options has no call")
        arguments = {k: v for k, v in self.arguments.items() if k not in self.drop}
        arguments[self.slot] = option.value
        return self.tool, arguments


# --------------------------------------------------------------------------------------
# What is open after a tool call
# --------------------------------------------------------------------------------------


def _words(*texts: object) -> list[str]:
    found: list[str] = []
    for text in texts:
        if text is None:
            continue
        found += [w for w in re.findall(r"[a-z0-9]+", normalize(str(text))) if w not in FILLER]
    return list(dict.fromkeys(found))


def date_option(day: dt.date) -> Option:
    weekday = WEEKDAY_NAMES_TR[day.weekday()]
    label = f"{day.isoformat()} {weekday}"
    month = MONTH_NAMES_TR[day.month - 1]
    return Option(label, [day.isoformat()], _words(weekday, day.day, month, day.isoformat()))


def _candidate_option(tool: str, item: dict[str, Any]) -> tuple[str, list[str], Option] | None:
    """(slot, dropped arguments, option) for one entry of a tool's `candidates`."""
    if "block_id" in item:
        label = f"{item.get('title')} {item.get('weekday')} {item.get('start')}-{item.get('end')}"
        start = str(item.get("start") or "")
        keys = _words(item.get("title"), item.get("kind"), item.get("weekday"), start)
        keys += [start.split(":")[0].lstrip("0")] if start else []
        return "block", ["on_weekday"], Option(label, f"#{item['block_id']}", keys)
    if "code" in item and "name" in item:
        label = f"{item['code']} {item['name']}"
        return "course", [], Option(label, item["code"], _words(item["code"], item["name"]))
    for id_field, text_field, drop in (
        ("task_id", "title", ["title"]),
        ("followup_id", "title", ["title"]),
        ("memory_id", "content", ["about"]),
    ):
        if id_field in item:
            label = str(item.get(text_field) or item[id_field])
            return id_field, drop, Option(label, item[id_field], _words(item.get(text_field)))
    return None


def observe(
    agent_id: str, request: str, tool: str, arguments: dict[str, Any] | None, result: dict[str, Any]
) -> PendingAction | None:
    """The open question a tool result leaves, as the call that would close it."""
    args = dict(arguments or {})
    if tool == "log_attendance" and "error" not in result:
        problems = result.get("not_logged") or []
        with_suggestions = [p for p in problems if p.get("suggest")]
        if len(with_suggestions) != 1:  # several days off at once: the yaver asks in words
            return None
        options = []
        for label in with_suggestions[0]["suggest"]:
            try:
                options.append(date_option(dt.date.fromisoformat(str(label).split()[0])))
            except ValueError:
                return None
        return PendingAction(
            agent_id, request, tool=tool, arguments=args, slot="dates", options=options
        )
    candidates = result.get("candidates")
    if "error" in result and isinstance(candidates, list) and len(candidates) >= 2:
        built = [_candidate_option(tool, c) for c in candidates if isinstance(c, dict)]
        if not built or any(b is None for b in built):
            return None
        slots = {b[0] for b in built if b}
        if len(slots) != 1:
            return None
        slot = slots.pop()
        drop = next(b[1] for b in built if b)
        return PendingAction(
            agent_id,
            request,
            tool=tool,
            arguments=args,
            slot=slot,
            drop=drop,
            options=[b[2] for b in built if b],
        )
    return None


def proposal_pending(agent_id: str, request: str, proposal_id: int) -> PendingAction:
    """A table shown for confirmation: "evet" saves it."""
    return PendingAction(
        agent_id,
        request,
        tool="apply_proposal",
        arguments={},
        slot="proposal_id",
        options=[Option(f"öneri #{proposal_id}", proposal_id, [])],
    )


# --------------------------------------------------------------------------------------
# Binding the user's answer
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class Binding:
    kind: str  # "option" | "decline" | "reply" (short, unmatched) | "other" (not an answer)
    option: Option | None = None


_WEEKDAY_WORDS = tuple(normalize(name) for name in WEEKDAY_NAMES_TR)


def _key_match(word: str, key: str) -> bool:
    if word == key:
        return True
    if any(len(w) > len(key) and w.startswith(key) and word.startswith(w) for w in _WEEKDAY_WORDS):
        return False  # "pazartesi" is not "pazar" + suffix (cumartesi / cuma alike)
    # Turkish suffixes: "çarşambaya", "lab'ı" -> "carsambaya", "labi"; digits stay exact
    return not word.isdigit() and not key.isdigit() and len(key) >= 3 and word.startswith(key)


def bind(pending: PendingAction, text: str) -> Binding:
    if "?" in text:
        return Binding("other")
    words = re.findall(r"[a-z0-9]+", normalize(text))
    if not words or len(words) > MAX_REPLY_WORDS:
        return Binding("other")
    if any(w in NO for w in words):
        return Binding("decline")
    options = pending.options
    if not options or pending.tool is None:
        return Binding("reply")

    yes = False
    ordinal: int | None = None
    meaningful: list[str] = []
    for word in words:
        if word in YES:
            yes = True
        elif word in ORDINAL_WORDS:
            ordinal = ORDINAL_WORDS[word]
        elif word in LAST_WORDS:
            ordinal = len(options)
        elif word in FILLER:
            continue
        elif word.isdigit() and not any(word in o.keys for o in options):
            ordinal = int(word)  # "2.si", "2" (a day number like "18" is a key instead)
        else:
            meaningful.append(word)

    def explains(option: Option) -> bool:
        return all(any(_key_match(w, k) for k in option.keys) for w in meaningful)

    if ordinal is not None:
        if not 1 <= ordinal <= len(options):
            return Binding("reply")
        chosen = options[ordinal - 1]
        return Binding("option", chosen) if explains(chosen) else Binding("reply")
    if not meaningful:
        if yes and len(options) == 1:
            return Binding("option", options[0])
        return Binding("reply")
    fitting = [o for o in options if explains(o)]
    if len(fitting) == 1:
        return Binding("option", fitting[0])
    return Binding("reply")


def done_note(tool: str, arguments: dict[str, Any], result_json: str) -> str:
    return (
        "Kullanıcının bu mesajı, önceki sorunun cevabı. Cevabına göre iş şimdi, bu mesajda "
        f"yapıldı: {tool}({arguments}) -> {result_json}\n"
        'Bunu az önce sen yaptın: birinci şahısla, kısa ve Türkçe bildir ("kaydettim"); '
        '"zaten" ya da "önceden" deme. Yalnızca bu sonuçta olanı yaz.'
    )


def reply_note(pending: PendingAction) -> str:
    choices = "; ".join(o.label for o in pending.options)
    extra = f" Seçenekler: {choices}." if choices else ""
    return (
        "Kullanıcının bu kısa mesajı, senin son sorunun cevabı." + extra + " Cevaba göre "
        "işi şimdi araçla tamamla; aynı soruyu tekrar sorma. Cevap soruyla ilgisizse ona göre "
        "davran."
    )
