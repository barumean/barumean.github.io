import fs from 'fs';
import {CANON} from './config.mjs';
import * as M from './model2.mjs';
const {D,value,calcNbar,ITEM,MG}=M;
Object.assign(M.CAL, CANON);
calcNbar();
const B=JSON.parse(fs.readFileSync('item_blocks.json','utf8'));
const OPPIT=B.OPPIT, N=D.length;
const MCOL=[]; D.forEach((m,i)=>{ if(MG[m.ko]) MCOL.push(i); });
const ci={}; MCOL.forEach((j,k)=>ci[j]=k);
const enc=Ms=>Ms.map(r=>r.map(v=>{const i=Math.round(Math.max(-1,Math.min(1,v))*20)+20;
  return String.fromCharCode(i<26?65+i:71+i);}).join('')).join('');
/* 내가 메가 · 상대는 실채용 아이템 — 100행 중 메가 가능한 행만 */
const VMO=MCOL.map(i=>{const r=[];for(let j=0;j<N;j++)r.push(value(i,j,1,0,0,OPPIT[j]));return r;});
/* 상대가 메가(아이템 칸은 스톤) · 나는 아이템 c — 100행 × 메가 가능한 열 */
const VOM={};
for(let c=0;c<ITEM.length;c++){
  VOM[c]=[]; for(let i=0;i<N;i++){const r=[];for(const j of MCOL)r.push(value(i,j,0,1,c,0));VOM[c].push(r);}
}
/* 둘 다 메가 */
const VMM=MCOL.map(i=>MCOL.map(j=>value(i,j,1,1,0,0)));
const EFF=JSON.parse(fs.readFileSync('effmega.json','utf8'));
fs.writeFileSync('mega_blocks.json',JSON.stringify({
  MCOL, EFF, VMO:enc(VMO), VOM:Object.fromEntries(Object.entries(VOM).map(([c,m])=>[c,enc(m)])), VMM:enc(VMM)
}));
console.log('메가 가능 개체',MCOL.length,'종');
console.log('VMO',MCOL.length+'x'+N,' VOM',(ITEM.length)+'개 클래스 x '+N+'x'+MCOL.length,' VMM',MCOL.length+'x'+MCOL.length);
console.log('블록 크기', fs.statSync('mega_blocks.json').size);
/* 상대가 메가하면 얼마나 세지는가 */
const IV=JSON.parse(fs.readFileSync('item_blocks.json','utf8'));
const dq=c=>(((c>96?c-71:c-65))-20)/20;
const base=IV.VOPP;
let rows=[];
for(const j of MCOL){
  let s=0,sm=0;
  for(let i=0;i<N;i++){ if(i===j)continue; s+=dq(base.charCodeAt(i*N+j)); sm+=VOM[0][i][ci[j]]; }
  rows.push([D[j].ko, (s/(N-1)).toFixed(3), (sm/(N-1)).toFixed(3), ((s-sm)/(N-1)).toFixed(3)]);
}
rows.sort((a,b)=>b[3]-a[3]);
console.log('\n메가진화로 상대가 얻는 이득 (내가 그 상대를 상대로 얻는 값의 하락폭) 상위 10:');
rows.slice(0,10).forEach(r=>console.log('  '+r[0].padEnd(14)+'기본 '+r[1]+' → 메가 '+r[2]+'   이득 '+r[3]));
console.log('하위 3:'); rows.slice(-3).forEach(r=>console.log('  '+r[0].padEnd(14)+'기본 '+r[1]+' → 메가 '+r[2]+'   이득 '+r[3]));
