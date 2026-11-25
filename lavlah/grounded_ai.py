"""Offline selection-only AI pilot. Adapter output cannot supply facts or citations."""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID
from urllib.parse import urlsplit
import unicodedata
from lavlah.mongolian_qa import interpret

FIELDS=("organization_id","name","category_slug","description","source_url","verified_at","expires_at")
# Synthetic integer micro-MNT rates, not actual provider pricing or a user charge.
INPUT_RATE=2
OUTPUT_RATE=5

@dataclass(frozen=True)
class Selection:
    ids: tuple
    input_units: int
    output_units: int

class MockAdapter:
    def select(self,query,choices):
        # No external call; immutable choices contain only IDs and names.
        return Selection(tuple(i for i,_ in choices[:3]),
                         len(query)+sum(len(name)+len(i) for i,name in choices),
                         sum(len(i) for i,_ in choices[:3]))

def normalize(text):
    return unicodedata.normalize("NFKC",text).casefold()

def ranked_rows(rows,query,now):
    clean={}
    for row in rows[:20]:
        try:
            item={k:row[k] for k in FIELDS}
            key=str(UUID(str(item["organization_id"])))
            url=urlsplit(item["source_url"])
            if url.scheme not in ("http","https") or not url.hostname or url.username or url.password:
                continue
            if not item["verified_at"]<=now<item["expires_at"]:
                continue
            if not isinstance(item["name"],str) or not isinstance(item["description"],str):
                continue
            name=normalize(item["name"])
            if query not in name:
                continue
            item["organization_id"]=key
            clean.setdefault(key,item)
        except (ValueError,TypeError,KeyError,AttributeError):
            continue
    return sorted(clean.values(),key=lambda row:(
        normalize(row["name"])!=query,
        not normalize(row["name"]).startswith(query),
        len(row["name"]),normalize(row["name"]),row["organization_id"]))[:5]

def validate_selection(selection,allowed):
    if not isinstance(selection,Selection) or type(selection.ids) is not tuple:
        raise ValueError("Invalid adapter selection")
    ids=selection.ids
    if not 1<=len(ids)<=3 or any(type(i) is not str or i not in allowed for i in ids) or len(set(ids))!=len(ids):
        raise ValueError("Unknown or duplicate citation")
    for units in (selection.input_units,selection.output_units):
        if type(units) is not int or not 0<=units<=10000:
            raise ValueError("Invalid mock usage")
    return ids

def respond(question,search,adapter=None,*,now=None):
    query=interpret(question)
    usage={"mode":"mock","attempts":0,"input_units":0,"output_units":0,"estimated_micro_mnt":0,"actual_charge_mnt":0,"outcome":"not_called"}
    result={"status":"clarify","answer":"Байгууллага эсвэл үйлчилгээний нэрийг тодруулна уу. Баталгаагүй үнэ, утас, хаяг өгөхгүй.","items":[],"usage":usage}
    if not query:
        return result
    now=now or datetime.now(timezone.utc)
    rows=ranked_rows(search(query,"",20,0),query,now)
    if not rows:
        result.update(status="no_result",answer="Баталгаажсан тохирох мэдээлэл олдсонгүй.")
        return result
    allowed={r["organization_id"]:r for r in rows}
    choices=tuple((r["organization_id"],r["name"]) for r in rows)
    usage["attempts"]=1
    try:
        selected=(adapter if adapter is not None else MockAdapter()).select(query,choices)
        ids=validate_selection(selected,allowed)
        usage.update(input_units=selected.input_units,output_units=selected.output_units,
                     estimated_micro_mnt=selected.input_units*INPUT_RATE+selected.output_units*OUTPUT_RATE,
                     outcome="selected")
    except Exception:
        # Never return adapter text or exception details. Unknown consumption is not zero cost.
        ids=tuple(allowed)[:3]
        usage.update(outcome="fallback",input_units=None,output_units=None,estimated_micro_mnt=None)
    result.update(status="matched",answer="Баталгаажсан лавлахын тохирох бүртгэлүүд:",
                  items=[allowed[i] for i in ids])
    return result
