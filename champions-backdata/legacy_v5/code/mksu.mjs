import fs from 'fs';
import {CANON} from './config.mjs';
import * as M from './model2.mjs';
const {D,ttk,calcNbar}=M;
Object.assign(M.CAL, CANON);
calcNbar();
const IT=JSON.parse(fs.readFileSync('item_blocks.json','utf8'));
const OPPIT=IT.OPPIT, N=D.length;
const ch=i=>String.fromCharCode(i<26?65+i:71+i);
const SUMON=[], SUTK={};
D.forEach((m,j)=>{
  if(!m.su) return;
  SUMON.push([j, m.su.mv, Math.round(m.su.p*1000)/10, m.su.mul]);
  const row=[];
  for(let a=0;a<N;a++){
    if(a===j){row.push(0);continue}
    // 1턴 쌓고, 강화된 화력으로 a를 넘기는 데 걸리는 총 턴수
    const t=1+ttk(j,a,0,0,OPPIT[j],0,m.su.mul);
    row.push(Math.max(1,Math.min(40,Math.round(t))));
  }
  SUTK[j]=row.map(ch).join('');
});
fs.writeFileSync('su_blocks.json',JSON.stringify({SUMON,SUTK}));
console.log('쌓기 개체',SUMON.length,' 파일',fs.statSync('su_blocks.json').size);
console.log(SUMON.slice(0,8).map(x=>D[x[0]].ko+' '+x[1]+' '+x[2]+'% ×'+x[3]).join(' · '));
