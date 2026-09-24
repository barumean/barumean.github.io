import fs from 'fs';
import {CANON} from './config.mjs';
import * as M from './model2.mjs';
const {D,movesTTK,calcNbar}=M;
Object.assign(M.CAL, CANON);
calcNbar();
const B=JSON.parse(fs.readFileSync('item_blocks.json','utf8'));
const USE=JSON.parse(fs.readFileSync('usage100.json','utf8'));
const ALL=JSON.parse(fs.readFileSync('allmoves100.json','utf8'));
const OPPIT=B.OPPIT, N=D.length;
const ch=i=>String.fromCharCode(i<26?65+i:71+i);            // 0..40
/* 개체별 전체 기술 채용률 (변화기 포함) */
const MVU={};
D.forEach(m=>{
  const all=(USE[m.ko]&&USE[m.ko].all)||{};
  const o={};
  for(const mv of (ALL[m.ko]||[])) o[mv]=Math.round((all[mv]??0)*10)/10;
  MVU[m.ko]=o;
});
/* 개체 × 공격기술 × 100상대 = 필요 턴수 */
const MVT={}; let cells=0, zero=0;
D.forEach((m,i)=>{
  const rows={};
  for(const mv of m.atkMoves) rows[mv]=new Array(N).fill(0);
  for(let j=0;j<N;j++){
    if(i===j) continue;
    const t=movesTTK(i,j,OPPIT[j]);
    for(const mv of m.atkMoves){
      const v=t[mv];
      rows[mv][j]= v===undefined?0:Math.max(1,Math.min(40,v));
      cells++; if(rows[mv][j]===0) zero++;
    }
  }
  const out={};
  for(const mv of m.atkMoves) out[mv]=rows[mv].map(ch).join('');
  MVT[m.ko]=out;
});
fs.writeFileSync('mv_blocks.json',JSON.stringify({MVU,MVT}));
console.log('칸',cells,'무효(0)',zero,'  파일',fs.statSync('mv_blocks.json').size);
/* 검산: 상위 4기만 들었을 때 3턴 이내에 넘기는 메타 비율 */
const FREQ=JSON.parse(fs.readFileSync('opps100.json','utf8')).flat();
const cnt=new Array(N).fill(0); for(const x of FREQ) cnt[x]++;
const W=cnt.map(c=>c+1), SW=W.reduce((a,b)=>a+b,0);
const rows=D.map((m,i)=>{
  const u=MVU[m.ko];
  const top4=Object.entries(u).sort((a,b)=>b[1]-a[1]).slice(0,4).map(x=>x[0]);
  const atk=top4.filter(x=>MVT[m.ko][x]);
  let cov=0, w=0;
  for(let j=0;j<N;j++){ if(i===j)continue;
    const t=Math.min(...atk.map(x=>{const v=MVT[m.ko][x].charCodeAt(j);const n=v>96?v-71:v-65;return n||99;}),99);
    if(t<=3){cov++; w+=W[j];}
  }
  return [m.ko, m.rank, atk.length, cov, (w/(SW-W[i])*100).toFixed(0), top4.join('·')];
});
console.log('\n실채용 상위 4기 기준 — 3턴 이내에 넘기는 메타 개체 수');
console.log('  최고:'); rows.slice().sort((a,b)=>b[3]-a[3]).slice(0,5).forEach(r=>console.log('    '+r[0].padEnd(12)+r[3]+'마리(등장률가중 '+r[4]+'%)  공격기 '+r[2]+'칸  '+r[5]));
console.log('  최저:'); rows.slice().sort((a,b)=>a[3]-b[3]).slice(0,5).forEach(r=>console.log('    '+r[0].padEnd(12)+r[3]+'마리(등장률가중 '+r[4]+'%)  공격기 '+r[2]+'칸  '+r[5]));
