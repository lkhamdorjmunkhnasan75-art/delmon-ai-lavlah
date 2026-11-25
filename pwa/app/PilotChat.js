"use client";
import {useEffect,useRef,useState} from "react";
function safeSource(value){try{const u=new URL(value);return ["https:","http:"].includes(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;}}
function date(value){const d=new Date(value);return Number.isFinite(d.valueOf())?d.toLocaleString("mn-MN",{timeZone:"Asia/Ulaanbaatar"}):"Тодорхойгүй";}
export default function PilotChat(){
 const [question,setQuestion]=useState(""),[turns,setTurns]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const active=useRef(null),seq=useRef(0);
 const [identityMode,setIdentityMode]=useState(false),[identityInput,setIdentityInput]=useState("");
 const [password,setPassword]=useState(""),[token,setToken]=useState(""),[authBusy,setAuthBusy]=useState(false);
 async function login(e){e.preventDefault();if(authBusy)return;setAuthBusy(true);setError("");try{const r=await fetch("/api/pilot/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password}),cache:"no-store",signal:AbortSignal.timeout(10000)});if(!r.ok)throw Error();const d=await r.json();if(typeof d.token!=="string")throw Error();setToken(d.token);}catch{setError("Нэвтрэх боломжгүй. Дахин оролдоно уу.");}finally{setPassword("");setAuthBusy(false);}}
 async function identityLogin(e){e.preventDefault();if(authBusy)return;setAuthBusy(true);setError("");try{const r=await fetch("/api/pilot/identity-check",{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer "+identityInput},body:"{}",cache:"no-store",signal:AbortSignal.timeout(8000)});if(!r.ok)throw Error();setToken(identityInput);}catch{setError("Identity баталгаажсангүй.");}finally{setIdentityInput("");setAuthBusy(false);}}
 async function logout(){clear();const old=token;setToken("");try{const r=await fetch(identityMode?"/api/pilot/identity-revoke":"/api/pilot/logout",{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer "+old},body:"{}",signal:AbortSignal.timeout(5000)});if(!r.ok)throw Error();}catch{setError("Төхөөрөмжөөс гарлаа. Серверийн session хүчингүй болсон эсэх баталгаажаагүй.");}}
 useEffect(()=>()=>{seq.current++;active.current?.abort();},[]);
 useEffect(()=>{if(!token||!identityMode)return;let ms=0;try{const p=JSON.parse(atob(token.split(".")[1].replace(/-/g,"+").replace(/_/g,"/")));ms=Math.max(0,p.exp*1000-Date.now());}catch{}const timer=setTimeout(()=>{clear();setToken("");setError("Session дууслаа. Дахин нэвтэрнэ үү.");},Math.min(ms,300000));return()=>clearTimeout(timer);},[token,identityMode]);
 async function ask(e){
  e.preventDefault();const q=question.trim();if(!q||active.current||!token)return;
  const id=++seq.current,controller=new AbortController();active.current=controller;setBusy(true);setError("");setQuestion("");
  const timer=setTimeout(()=>controller.abort(),10000);
  try{
   const r=await fetch(identityMode?"/api/pilot/identity-chat":"/api/pilot/ask",{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer "+token},body:JSON.stringify({question:q}),signal:controller.signal,cache:"no-store"});
   if(id!==seq.current)return;
   if(r.status===401){clear();setToken("");setError("Session дууслаа. Дахин нэвтэрнэ үү.");return;}
   if(identityMode&&r.status===422){setError("Хувийн мэдээлэл эсвэл заавар агуулсан асуулт зөвшөөрөхгүй.");return;}if(r.status===429){setError("Хүсэлтийн хязгаарт хүрлээ. Түр хүлээгээд дахин асууна уу.");setQuestion(q);return;}if(!r.ok)throw Error();const d=await r.json();
   if(!["matched","clarify","no_result"].includes(d.status)||typeof d.answer!=="string"||!Array.isArray(d.items)||d.items.length>3)throw Error();
   if(id===seq.current)setTurns(old=>[...old.slice(-19),{id,q:identityMode?"Асуулт илгээсэн":q,data:d,rating:0}]);
  }catch{if(id===seq.current){setError("Түр алдаа гарлаа. Асуултаа дахин илгээнэ үү.");setQuestion(q);}}
  finally{clearTimeout(timer);if(id===seq.current){active.current=null;setBusy(false);}}
 }
 async function rate(t,rating){const generation=seq.current;if(identityMode){try{const r=await fetch("/api/pilot/identity-feedback",{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer "+token},body:JSON.stringify({usage_id:t.data.usage_id,rating}),signal:AbortSignal.timeout(5000)});if(!r.ok)throw Error();}catch{if(generation===seq.current)setError("Үнэлгээ хадгалагдсангүй.");return;}}if(generation===seq.current)setTurns(old=>old.map(x=>x.id===t.id?{...x,rating}:x));}
 function clear(){seq.current++;active.current?.abort();active.current=null;setBusy(false);setError("");setTurns([]);setQuestion("");}
 return <section className="pilot-chat" aria-label="DELMON чат"><h2>DELMON чат</h2><p>Туршилтын горим · Зохиомол өгөгдөл · Төлбөргүй</p>
 {!token?<><button type="button" onClick={()=>{setIdentityMode(v=>!v);setPassword("");setIdentityInput("");setError("");}}>{identityMode?"Туршилтын код ашиглах":"Identity token ашиглах"}</button>{identityMode?<form onSubmit={identityLogin}><label htmlFor="identity-token">Туршилтын identity token</label><input id="identity-token" type="password" autoComplete="off" maxLength={4096} value={identityInput} onChange={e=>setIdentityInput(e.target.value)} required/><button disabled={authBusy||!identityInput}>Identity нэвтрэх</button></form>:<form onSubmit={login}><label htmlFor="pilot-password">Туршилтын нэвтрэх код</label><input id="pilot-password" type="password" autoComplete="off" maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} required/><button disabled={authBusy||!password}>Нэвтрэх</button></form>}</>:<><button type="button" onClick={logout}>Гарах</button>
 <button type="button" onClick={clear}>Чат цэвэрлэх</button>
 <div aria-live="polite" aria-label="Чатын хариулт">{turns.map(t=><article className="chat-turn" key={t.id}><p className="chat-question"><strong>Та:</strong> {t.q}</p><p><strong>DELMON:</strong> {t.data.answer}</p>
 {t.data.status==="matched"&&t.data.items.map((item,i)=><div className="chat-source" key={i}><h3>{item.name}</h3><p>{item.description}</p>{safeSource(item.source_url)&&<a href={safeSource(item.source_url)} target="_blank" rel="noopener noreferrer">Эх сурвалж</a>}<p>Баталгаажсан: {date(item.verified_at)}<br/>Хүчинтэй хүртэл: {date(item.expires_at)}</p></div>)}
 <div className="chat-feedback" role="group" aria-label="Хариултын үнэлгээ"><button type="button" aria-pressed={t.rating===1} onClick={()=>rate(t,1)}>Тустай</button><button type="button" aria-pressed={t.rating===-1} onClick={()=>rate(t,-1)}>Тусгүй</button></div>{t.rating!==0&&<p role="status">{identityMode?"Үнэлгээ серверт хадгалагдлаа.":"Үнэлгээ энэ чатад хадгалагдлаа."}</p>}</article>)}</div>
 <form onSubmit={ask}><label htmlFor="pilot-question">Асуултаа бичнэ үү</label><textarea id="pilot-question" maxLength={240} rows={3} value={question} disabled={busy} onChange={e=>setQuestion(e.target.value)} required/><button type="submit" disabled={busy||!question.trim()}>Асуух</button></form>
 {busy&&<p role="status">Хариулт бэлтгэж байна…</p>}</>}{error&&<p role="alert">{error}</p>}
 </section>;
}
