export const dynamic="force-dynamic";
const noStore={"Cache-Control":"no-store"};
export async function GET(request,{params}){
 const {parts=[]}=await params;
 if(parts.length>1||(parts.length===1&&parts[0]!=="categories"))return Response.json({error:"Not found"},{status:404,headers:noStore});
 const origin=process.env.LAVLAH_API_ORIGIN;
 try{
  if(!origin)throw Error("missing upstream");
  const url=new URL(parts.length?"/v1/directory/categories":"/v1/directory",origin);
  const search=new URL(request.url).searchParams;
  if(!parts.length)for(const key of ["q","category","limit","offset"]){if(search.has(key))url.searchParams.set(key,search.get(key));}
  const response=await fetch(url,{cache:"no-store",redirect:"error",signal:AbortSignal.timeout(6000),headers:{Accept:"application/json"}});
  if(!response.ok)return Response.json({error:"Directory unavailable"},{status:response.status===422?422:503,headers:noStore});
  return Response.json(await response.json(),{headers:noStore});
 }catch{return Response.json({error:"Directory unavailable"},{status:503,headers:noStore});}
}
