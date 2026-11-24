import {connection} from "next/server";
import "./style.css";
export const metadata={title:"DELMON LAVLAH",description:"Баталгаажсан байгууллагын лавлах",manifest:"/manifest.webmanifest",appleWebApp:{capable:true,title:"DELMON LAVLAH"},icons:{apple:"/icon-192.png"}};
export const viewport={themeColor:"#086b61"};
export default async function Layout({children}){await connection();return <html lang="mn"><body>{children}</body></html>;}
