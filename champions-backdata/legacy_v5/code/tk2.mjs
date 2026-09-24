import fs from 'fs';
import {CANON} from './config.mjs';
import * as M from './model2.mjs';
const {D,ttk,calcNbar}=M; const C=M.CAL;
Object.assign(M.CAL, CANON); calcNbar();
const W=JSON.parse(fs.readFileSync('oppw100.json','utf8'));
const TK={};
D.forEach((d,i)=>{
  let nuke=0,frail=0,tank=0,zw=0,nw=0,fw=0,tw=0;
  for(let j=0;j<100;j++){
    if(i===j)continue;
    const a=ttk(i,j,0,0), b=ttk(j,i,0,0);
    zw+=W[j];
    if(a<=1.5){nuke++;nw+=W[j];}
    if(b<=1.5){frail++;fw+=W[j];}
    if(b>=3){tank++;tw+=W[j];}
  }
  TK[d.ko]=[nuke,frail,tank,+(nw/zw).toFixed(3),+(fw/zw).toFixed(3),+(tw/zw).toFixed(3)];
});
fs.writeFileSync('tk100.json',JSON.stringify(TK));
const e=Object.entries(TK);
console.log('원턴킬 최다:',[...e].sort((a,b)=>b[1][0]-a[1][0]).slice(0,5).map(x=>x[0]+' '+x[1][0]).join(' / '));
console.log('내구(3방+) 최다:',[...e].sort((a,b)=>b[1][2]-a[1][2]).slice(0,5).map(x=>x[0]+' '+x[1][2]).join(' / '));
console.log('원턴킬 피격 최다:',[...e].sort((a,b)=>b[1][1]-a[1][1]).slice(0,5).map(x=>x[0]+' '+x[1][1]).join(' / '));
