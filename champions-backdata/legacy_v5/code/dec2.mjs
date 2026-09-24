import fs from 'fs';
const blocks=fs.readFileSync('all2.txt','utf8').split(/^###/m).filter(s=>s.trim());
function decode(pairs,target,cap){
  const cands=pairs.map(([n,s],k)=>{
    const out=[];
    for(let r=k+1;r<=Math.min(k+3,12);r++){const pre=String(r);
      if(s.startsWith(pre)){const t=s.slice(pre.length);const v=parseFloat(t);
        if(t!==''&&!isNaN(v)&&v>=0&&v<=100)out.push({v,cost:(r-(k+1))*0.5})}}
    const raw=parseFloat(s); if(!isNaN(raw)&&raw>=0&&raw<=100)out.push({v:raw,cost:1});
    return out;
  });
  // 내림차순은 '강한 선호'지 절대 제약이 아니다 — 원본이 가끔 어긋난다
  let best=null;
  const rec=(k,prev,acc,sum,cost)=>{
    if(cost>6) return;
    if(k===pairs.length){
      let sc=cost+(target?Math.abs(sum-target)/40:0);
      if(cap&&sum>cap) sc+=50;          // 4칸을 넘는 합은 물리적으로 불가능
      if(!best||sc<best.sc-1e-9||(Math.abs(sc-best.sc)<1e-9&&sum>best.sum))best={sc,sum,vals:acc.slice()};
      return;}
    for(const c of cands[k]){
      const pen = c.v<=prev+1e-9 ? 0 : 1.2;      // 역전이면 벌점
      acc.push(c.v); rec(k+1,Math.min(prev,c.v),acc,sum+c.v,cost+c.cost+pen); acc.pop();
    }
  };
  rec(0,101,[],0,0);
  return best;
}
const P=s=>s?s.split(';').filter(Boolean).map(t=>{const i=t.lastIndexOf('^');return [t.slice(0,i).trim(), t.slice(i+1).trim().replace(/%.*$/,'')]}):[];
const OUT={},BAD=[];
for(const b of blocks){
  const L=b.trim().split('\n');
  const [rank,slug,ko]=L[0].split('|');
  const g=p=>(L.find(x=>x.startsWith(p))||'').replace(p,'').trim();
  const types=g('TYPE:').split(',').map(s=>s.trim()).filter(Boolean);
  const stat=g('STAT:').split(',').map(Number);
  const mp=P(g('MOVES:')), ap=P(g('ABIL:')), ip=P(g('ITEM:'));
  const md=decode(mp,ko==='메타몽'?null:375,402), ad=decode(ap,100), id=decode(ip,100);
  const o={rank:+rank,slug,ko,types,stat,
    moves: md?Object.fromEntries(mp.map((p,i)=>[p[0],md.vals[i]])):null,
    abil:  ad?Object.fromEntries(ap.map((p,i)=>[p[0],ad.vals[i]])):null,
    item:  id?Object.fromEntries(ip.map((p,i)=>[p[0],id.vals[i]])):null,
    msum:md?+md.sum.toFixed(1):null, asum:ad?+ad.sum.toFixed(1):null, isum:id?+id.sum.toFixed(1):null};
  OUT[ko]=o;
  const ok = (ko==='메타몽'||(md&&md.sum>=140&&md.sum<=410)) && ad&&ad.sum>=93&&ad.sum<=107 && id&&id.sum>=80&&id.sum<=112
     && types.length>=1 && stat.length===6 && stat.every(x=>x>0);
  if(!ok) BAD.push(`${rank}|${slug}|${ko} moves=${o.msum} abil=${o.asum} item=${o.isum} type=${types.length} stat=${stat.length}`);
}
fs.writeFileSync('dex2.json',JSON.stringify(OUT));
console.log('블록',Object.keys(OUT).length,' 검증실패',BAD.length); BAD.forEach(x=>console.log('  '+x));
const ms=Object.values(OUT).filter(o=>o.msum).map(o=>o.msum).sort((a,b)=>a-b);
console.log('기술합 중앙',ms[50],'범위',ms[0],'~',ms[ms.length-1]);
console.log('\n잠만보:',JSON.stringify(OUT['잠만보'].moves));
console.log('보만다 아이템:',JSON.stringify(OUT['보만다'].item));
