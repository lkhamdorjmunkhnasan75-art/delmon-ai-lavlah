export const dynamic="force-dynamic";
const headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"};
const reply=(body,status)=>Response.json(body,{status,headers});
export async function POST(request){
 if(process.env.LAVLAH_ENABLE_PILOT_CHAT!=="1")return reply({error:"Not found"},404);
 if(request.headers.get("origin")!==new URL(request.url).origin)return reply({error:"Forbidden"},403);
 if(!/^application\/json(?:;|$)/i.test(request.headers.get("content-type")||""))return reply({error:"Invalid input"},415);
 try{
  const reader=request.body?.getReader();if(!reader)return reply({error:"Invalid input"},400);
  let size=0;const decoder=new TextDecoder("utf-8",{fatal:true});let raw="";
  while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>4096){await reader.cancel();return reply({error:"Too large"},413);}raw+=decoder.decode(value,{stream:true});}
  raw+=decoder.decode();const body=JSON.parse(raw);
  if(!body||typeof body.question!=="string"||Object.keys(body).length!==1||!body.question.trim()||body.question.length>240)return reply({error:"Invalid input"},422);
  const origin=new URL(process.env.LAVLAH_API_ORIGIN||"http://127.0.0.1:8000");
  if(origin.protocol!=="http:"||origin.hostname!=="127.0.0.1"||origin.username||origin.password)return reply({error:"Unavailable"},503);
  const upstream=await fetch(new URL("/v1/pilot/grounded-ask",origin),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:body.question}),cache:"no-store",redirect:"error",signal:AbortSignal.timeout(8000)});
  if(!upstream.ok)return reply({error:"Unavailable"},upstream.status===422?422:503);
  return reply(await upstream.json(),200);
 }catch{return reply({error:"Unavailable"},503);}
}
