import fs from 'fs';
const D=JSON.parse(fs.readFileSync('data100.json','utf8'));
const DX=JSON.parse(fs.readFileSync('raw2/dex2.json','utf8'));
const W=JSON.parse(fs.readFileSync('oppw100.json','utf8'));
const MVn=JSON.parse(fs.readFileSync('mv100.json','utf8'));
const ALL=JSON.parse(fs.readFileSync('allmoves100.json','utf8'));
const S=JSON.parse(fs.readFileSync('stats100.json','utf8'));
const TK=JSON.parse(fs.readFileSync('tk100.json','utf8'));
const MG=JSON.parse(fs.readFileSync('mega.json','utf8'));
const MS=JSON.parse(fs.readFileSync('megastats.json','utf8'));
const opps=JSON.parse(fs.readFileSync('opps100.json','utf8'));
const h=fs.readFileSync('champions-meta-50.html','utf8');
// 이전 DATA에서 폼 표기·특성 주석만 승계
const a=h.indexOf('const DATA='), e=h.indexOf('].map((r,i)=>',a)+1;
const OLD=eval(h.slice(a,e).replace('const DATA=',''));
const oldBy={}; OLD.forEach(r=>oldBy[r[0]]=r);
const FORM={"킬가르도":"실드폼","대쓰여너":"수컷의 모습","에써르(수컷)":"수컷의 모습","에써르(암컷)":"암컷의 모습",
 "대검귀":"히스이의 모습","플라엣테":"영원의 꽃","가라르야도킹":"가라르의 모습",
 "조로아크(히스이)":"히스이의 모습","미끄래곤(히스이)":"히스이의 모습","윈디(히스이)":"히스이의 모습",
 "알로라 나인테일":"알로라의 모습","스트린더(하이)":"하이한 모습","스트린더(로우)":"로우한 모습"};
const rows=D.map(d=>{
  const o=oldBy[d.ko];
  return [d.ko, FORM[d.ko]||"", d.en, d.types, Object.keys(DX[d.ko].abil||{}),
          Object.keys(DX[d.ko].item||{}).slice(0,3), ALL[d.ko]||[], o&&o[7]?o[7]:undefined];
});
// 순위 변동 배지 — 이전 DATA의 rank 대비
const oldRank={}; OLD.forEach((r,i)=>oldRank[r[0]]=i+1);
// 표기가 바뀐 개체는 이전 이름으로 대조
const RENAME={"에써르(암컷)":"에써르","조로아크(히스이)":"조로아크","미끄래곤(히스이)":"미끄래곤","윈디(히스이)":"윈디"};
for(const [nw,od] of Object.entries(RENAME)) if(oldRank[od]!==undefined) oldRank[nw]=oldRank[od];
const CHG={}; D.forEach(d=>{ const p=oldRank[d.ko];
  CHG[d.ko]= p===undefined?"New": p===d.rank?"=": (p>d.rank?"↑"+(p-d.rank):"↓"+(d.rank-p)); });
const q=x=>JSON.stringify(x);
fs.writeFileSync('blk_data.js','const CHG='+q(CHG)+';\nconst DATA=[\n'+rows.map(r=>'  '+q(r)).join(',\n')+'\n]');
const mir=new Array(100).fill(0); opps.forEach(o=>o.forEach(i=>mir[i]++));
fs.writeFileSync('blk_mx.js','const OPPS='+q(opps)+';\nconst MIR='+q(mir.map(x=>+(x/opps.length).toFixed(4)))+';\nconst OPPW='+q(W.map(x=>+x.toFixed(5)))+';\n');
fs.writeFileSync('blk_tk.js','const TK='+q(TK)+';\n');
fs.writeFileSync('blk_stats.js','const STATS='+q(S)+';\n');
fs.writeFileSync('blk_mv.js','const MV='+q(MVn)+';\n');
fs.writeFileSync('blk_mega.js','const MEGA='+q(MG)+';\n');
console.log('DATA',rows.length,'| 신규',Object.values(CHG).filter(x=>x==='New').length,'| MEGA',Object.keys(MG).length,'| OPPS',opps.length);
console.log('특성 비어있는 개체:',rows.filter(r=>r[4].length===0).length);
