const headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"};
const reply=(body,status)=>Response.json(body,{status,headers});
export async function forward(request,action){
 if(!["ask","login","logout"].includes(action))return reply({error:"Not found"},404);
 if(process.env.LAVLAH_ENV!=="pilot"||process.env.LAVLAH_PILOT_ONLY!=="1"||process.env.LAVLAH_ENABLE_PILOT_CHAT!=="1")return reply({error:"Not found"},404);
 // Next may reconstruct request.url with localhost rather than the incoming host.
 // Pin the trusted pilot browser origin explicitly; do not trust forwarded headers.
 const browserOrigin=process.env.PILOT_CHAT_ORIGIN||"http://127.0.0.1:3000";
 let expected;
 try{expected=new URL(browserOrigin);}catch{return reply({error:"Unavailable"},503);}
 if(expected.protocol!=="http:"||expected.hostname!=="127.0.0.1"||expected.origin!==browserOrigin)return reply({error:"Unavailable"},503);
 if(request.headers.get("origin")!==expected.origin||request.headers.get("host")!==expected.host)return reply({error:"Forbidden"},403);
 if(!/^application\/json(?:;|$)/i.test(request.headers.get("content-type")||""))return reply({error:"Invalid input"},415);
 try{
  const reader=request.body?.getReader();if(!reader)return reply({error:"Invalid input"},400);
  let timer;const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error("body_timeout")),4000);});
  let size=0;const decoder=new TextDecoder("utf-8",{fatal:true});let raw="";
  try{while(true){const {done,value}=await Promise.race([reader.read(),timeout]);if(done)break;size+=value.length;if(size>4096){void reader.cancel().catch(()=>{});return reply({error:"Too large"},413);}raw+=decoder.decode(value,{stream:true});}}catch{void reader.cancel().catch(()=>{});return reply({error:"Invalid or slow body"},408);}finally{clearTimeout(timer);}
  raw+=decoder.decode();const body=JSON.parse(raw);
  if(!body||typeof body!=="object"||Array.isArray(body)|| (action==="ask"?(typeof body.question!=="string"||Object.keys(body).length!==1||!body.question.trim()||body.question.length>240):action==="login"?(typeof body.password!=="string"||Object.keys(body).length!==1||body.password.length>128):Object.keys(body).length!==0))return reply({error:"Invalid input"},422);
  const origin=new URL(process.env.LAVLAH_API_ORIGIN||"http://127.0.0.1:8000");
  if(origin.protocol!=="http:"||origin.hostname!=="127.0.0.1"||origin.username||origin.password)return reply({error:"Unavailable"},503);
  const upstream=await fetch(new URL("/v1/pilot/"+(action==="ask"?"grounded-ask":action),origin),{method:"POST",headers:{"Content-Type":"application/json","Authorization":request.headers.get("authorization")||""},body:JSON.stringify(body),cache:"no-store",redirect:"error",signal:AbortSignal.timeout(8000)});
  if(upstream.status===429){const retry=upstream.headers.get("Retry-After");return Response.json({error:"Rate limited"},{status:429,headers:{...headers,"Retry-After":/^[1-9][0-9]?$/.test(retry||"")?retry:"60"}});}
  if(!upstream.ok)return reply({error:"Unavailable"},[401,403,408,413,422,504].includes(upstream.status)?upstream.status:503);
  return reply(await upstream.json(),200);
 }catch{return reply({error:"Unavailable"},503);}
}
