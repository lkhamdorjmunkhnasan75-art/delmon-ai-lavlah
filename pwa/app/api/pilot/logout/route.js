import {forward} from "../forward";
export const dynamic="force-dynamic";
export async function POST(request){return forward(request,"logout");}
