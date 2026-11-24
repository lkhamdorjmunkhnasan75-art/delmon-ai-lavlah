import {ImageResponse} from "next/og";
export async function GET(request,{params}){
 const {icon}=await params;
 const size=icon==="icon-192.png"?192:icon==="icon-512.png"?512:0;
 if(!size)return new Response("Not found",{status:404});
 return new ImageResponse(<div style={{width:"100%",height:"100%",display:"flex",alignItems:"center",justifyContent:"center",background:"#086b61",color:"white",fontSize:size*0.56,fontWeight:700}}>D</div>,{width:size,height:size});
}
