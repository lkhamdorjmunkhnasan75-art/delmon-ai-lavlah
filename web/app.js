"use strict";
const form=document.querySelector("#search"), input=document.querySelector("#q"), status=document.querySelector("#status"), results=document.querySelector("#results"), prev=document.querySelector("#prev"), next=document.querySelector("#next");
const limit=20;
let query="", offset=0, generation=0;
function node(tag,value){const e=document.createElement(tag);e.textContent=value;return e;}
function render(row){
 const card=document.createElement("article");
 card.append(node("h2",row.name),node("p",row.description||""),node("p","Ангилал: "+row.category_slug));
 try{const url=new URL(row.source_url);if(["https:","http:"].includes(url.protocol)){const a=node("a","Эх сурвалж");a.href=url.href;a.target="_blank";a.rel="noopener noreferrer";card.append(a);}}catch{}
 card.append(node("p","Баталгаажсан: "+new Date(row.verified_at).toLocaleDateString("mn-MN")));
 results.append(card);
}
async function search(){
 const current=++generation;
 prev.disabled=next.disabled=true;results.replaceChildren();status.textContent="Хайж байна…";
 try{
  const params=new URLSearchParams({q:query,limit:String(limit),offset:String(offset)});
  const response=await fetch("/v1/directory?"+params,{headers:{Accept:"application/json"}});
  if(!response.ok)throw Error("request");
  const data=await response.json();
  if(current!==generation)return;
  data.items.forEach(render);
  status.textContent=data.items.length?"Олдсон мэдээлэл: "+data.items.length:"Тохирох мэдээлэл олдсонгүй.";
  prev.disabled=offset===0;next.disabled=data.items.length<limit||offset+limit>10000;
 }catch{if(current!==generation)return;status.textContent="Түр алдаа гарлаа. Дахин хайна уу.";prev.disabled=offset===0;}
}
form.addEventListener("submit",event=>{event.preventDefault();query=input.value.trim();offset=0;search();});
prev.addEventListener("click",()=>{offset=Math.max(0,offset-limit);search();});
next.addEventListener("click",()=>{offset+=limit;search();});
