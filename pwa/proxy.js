import {NextResponse} from "next/server";
import {randomBytes} from "node:crypto";
export function proxy(request){
 const nonce=randomBytes(18).toString("base64");
 const policy="default-src 'self'; script-src 'self' 'nonce-"+nonce+"' 'strict-dynamic'; style-src 'self' 'nonce-"+nonce+"'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; worker-src 'self'";
 const headers=new Headers(request.headers);
 headers.set("Content-Security-Policy",policy);
 headers.set("x-nonce",nonce);
 const response=NextResponse.next({request:{headers}});
 response.headers.set("Content-Security-Policy",policy);
 response.headers.set("Cache-Control","private, no-store");
 return response;
}
export const config={matcher:"/"};
