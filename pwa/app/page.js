"use client";
import {useEffect,useRef,useState} from "react";
const labels={services:"Үйлчилгээ",trade:"Худалдаа",construction:"Барилга",education:"Боловсрол",health:"Эрүүл мэнд",transport:"Тээвэр",agriculture:"Хөдөө аж ахуй",technology:"Технологи",tourism:"Аялал жуулчлал",finance:"Санхүү",manufacturing:"Үйлдвэрлэл",mining:"Уул уурхай"};
const label=s=>Object.hasOwn(labels,s)?labels[s]:"Ангилал: "+s;
function safeLink(value){try{const u=new URL(value);return ["https:","http:"].includes(u.protocol)?u.href:null;}catch{return null;}}
export default function Home(){
 const [q,setQ]=useState(""),[category,setCategory]=useState(""),[categories,setCategories]=useState([]),[names,setNames]=useState({}),[categoryError,setCategoryError]=useState(false),[rows,setRows]=useState([]),[message,setMessage]=useState("Хайх нэрээ оруулна уу."),[busy,setBusy]=useState(false),[offset,setOffset]=useState(0),[hasNext,setHasNext]=useState(false),[install,setInstall]=useState(null),[installed,setInstalled]=useState(false);
 const displayLabel=s=>Object.hasOwn(names,s)&&/[А-Яа-яӨөҮүЁё]/u.test(names[s])?names[s]:Object.hasOwn(labels,s)?labels[s]:"Бусад ангилал ("+s+")";
 const sequence=useRef(0),active=useRef({q:"",category:""});
 useEffect(()=>{
  if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js").catch(()=>{});
  const handler=e=>{e.preventDefault();setInstall(e);}, done=()=>{setInstall(null);setInstalled(true);};
  window.addEventListener("beforeinstallprompt",handler);window.addEventListener("appinstalled",done);
  const controller=new AbortController();
  fetch("/api/directory/categories",{cache:"no-store",signal:controller.signal}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(d=>{setCategories(d.items);setNames(d.names||{});}).catch(()=>{if(!controller.signal.aborted)setCategoryError(true);});
  return ()=>{controller.abort();window.removeEventListener("beforeinstallprompt",handler);window.removeEventListener("appinstalled",done);};
 },[]);
 async function search(criteria,start){
  const id=++sequence.current;setBusy(true);setRows([]);setHasNext(false);setOffset(start);setMessage("Хайж байна…");
  try{const p=new URLSearchParams({...criteria,limit:"20",offset:String(start)});
   const r=await fetch("/api/directory?"+p,{cache:"no-store"});if(!r.ok)throw Error();const d=await r.json();if(id!==sequence.current)return;
   setRows(d.items);setHasNext(d.items.length===20&&start+20<=10000);setMessage(d.items.length?"Олдсон мэдээлэл: "+d.items.length:"Тохирох мэдээлэл олдсонгүй.");
  }catch{if(id===sequence.current)setMessage("Түр алдаа гарлаа. Дахин хайна уу.");}finally{if(id===sequence.current)setBusy(false);}
 }
 return <main><header><p className="brand">DELMON LAVLAH</p><h1>Хайх хэрэггүй.<br/>Асуухад л хангалттай.</h1><p>Баталгаажсан байгууллагын мэдээллийг хайх.</p>
 {install?<button onClick={async()=>{await install.prompt();setInstall(null);}}>Апп суулгах</button>:!installed&&<p>Суулгах бол браузерын цэснээс үндсэн дэлгэцэд нэмэх сонголтыг ашиглана уу.</p>}</header>
 <form onSubmit={e=>{e.preventDefault();active.current={q:q.trim(),category};search(active.current,0);}}>
 <label htmlFor="q">Байгууллагын нэр</label><input id="q" type="search" maxLength={120} value={q} onChange={e=>setQ(e.target.value)}/>
 <label htmlFor="category">Ангилал</label><select id="category" value={category} onChange={e=>setCategory(e.target.value)}><option value="">Бүх ангилал</option>{categories.map(s=><option key={s} value={s}>{displayLabel(s)}</option>)}</select>
 {categoryError&&<p role="status">Ангиллыг ачаалж чадсангүй. Нэрээр хайх боломжтой.</p>}<button type="submit">Хайх</button></form>
 <p id="status" role="status" aria-live="polite">{message}</p><section aria-label="Хайлтын үр дүн" id="results">{rows.map(row=><article key={row.organization_id}><h2>{row.name}</h2><p>{row.description}</p><p>{displayLabel(row.category_slug)}</p>{safeLink(row.source_url)&&<a href={safeLink(row.source_url)} target="_blank" rel="noopener noreferrer">Эх сурвалж</a>}<p>Баталгаажсан: {new Date(row.verified_at).toLocaleDateString("mn-MN")}</p></article>)}</section>
 <nav aria-label="Хуудаслалт"><button disabled={busy||offset===0} onClick={()=>search(active.current,Math.max(0,offset-20))}>Өмнөх</button><button disabled={busy||!hasNext} onClick={()=>search(active.current,offset+20)}>Дараах</button></nav>
 <footer>Зөвхөн баталгаажсан, нийтэд зөвшөөрсөн мэдээлэл. Интернэт холболт шаардлагатай.</footer></main>;
}
