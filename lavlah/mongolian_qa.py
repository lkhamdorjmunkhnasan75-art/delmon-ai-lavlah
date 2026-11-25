"""Bounded directory QA; no model, network fetch, payment or invented facts."""
import re
import unicodedata

ALIASES={"zaswariin":"засвар","zaswariig":"засвар","khukh tenger":"хөх тэнгэр","hurgeltiin":"хүргэлт","hudaldaanii":"худалдаа","altan nar":"алтан нар","hoh tenger":"хөх тэнгэр",
         "huh tenger":"хөх тэнгэр","zasvar":"засвар",
         "hudaldaa":"худалдаа","khudaldaa":"худалдаа",
         "surgalt":"сургалт","hurgelt":"хүргэлт","nogoon tal":"ногоон тал","tsagaan uul":"цагаан уул"}
STOP={"olch","olood","oloод","ugch","boloh","bolomjtoi","байгууллагын","компани","company","хаана","байна","уу","вэ","юу","олох","хайх","хайж","өгөөч",
      "байдаг","мэдээлэл","талаар","өгнө","үү","надад","хэрэгтэй",
      "haana","baina","ve","uu","haih","medeelel","байгаа","байдаг","хайгаад","хайгаач","хаанаас","тухай","hai","haanaas","heregtei","ugooch"}
UNSUPPORTED={"үнэ","үнэтэй","утас","хаяг","цаг","дугаар","баталгаа",
             "une","utas","hayag","tsag","dugaar","хэд","төгрөг","үнээр","утасны","хаягийг","hed","uneer","хэзээ"}
def interpret(question):
    if not isinstance(question,str) or not 1<=len(question)<=240:
        raise ValueError("Question must contain 1–240 characters")
    normalized=unicodedata.normalize("NFKC",question).casefold()
    if any(unicodedata.category(ch).startswith("C") for ch in normalized):
        raise ValueError("Invalid question characters")
    words=re.findall(r"[^\W_]+",normalized)
    if set(words)&UNSUPPORTED:
        return None
    # Only explicitly supported aliases; no speculative transliteration.
    phrase=" ".join(words)
    for latin,cyr in sorted(ALIASES.items(),key=lambda pair:-len(pair[0])):
        phrase=re.sub(r"(?<!\w)"+re.escape(latin)+r"(?!\w)",cyr,phrase)
    terms=[w for w in phrase.split() if w not in STOP]
    if not terms or len(terms)>8 or any(not re.fullmatch(r"[а-яёөү]+",w) for w in terms):
        return None
    query=" ".join(terms)
    return query if len(query)<=120 else None

def answer(question,search):
    """search is a trusted restricted public-directory reader."""
    query=interpret(question)
    if not query:
        return {"status":"clarify","answer":"Байгууллага эсвэл үйлчилгээний нэрийг тодруулна уу. Үнэ, утас, хаягийн баталгаатай мэдээлэл одоогоор байхгүй.","items":[]}
    rows=search(query,"",5,0)
    if not rows:
        return {"status":"no_result","answer":"Баталгаажсан тохирох мэдээлэл олдсонгүй.","items":[]}
    fields=("organization_id","name","category_slug","description","source_url","verified_at","expires_at")
    return {"status":"matched","answer":"Баталгаажсан лавлахын тохирох бүртгэлүүд:","items":[{k:r[k] for k in fields} for r in rows]}
