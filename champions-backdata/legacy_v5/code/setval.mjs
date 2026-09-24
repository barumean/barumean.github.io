import * as S from './setopt.mjs';
import * as M from './model2.mjs';
import fs from 'fs';
const {D,value,MG}=M;
const W=JSON.parse(fs.readFileSync('oppw100.json','utf8')), E=JSON.parse(fs.readFileSync('effmega.json','utf8'));
const SR=JSON.parse(fs.readFileSync('stonerate.json','utf8'));
S.OPT.prio=0; S.OPT.nuke=0; S.OPT.recoil=0;
let n=0,maxd=0;
for(let i=0;i<D.length&&n<8;i++){
  const A=D[i]; if(A.su||A.rec>0||A.ko==="메타몽") continue;
  if(A.atkMoves.some(m=>S.PRIO.has(m)||["오버히트","용성군","리프스톰","기가임팩트","파괴광선","엄청난힘","사이코부스트"].includes(m))) continue;
  const ctx=S.prep(i,["all"]);
  // 모델과 같은 공격기 전체를 세트로
  const set=A.atkMoves.filter(m=>ctx.cand.some(c=>c.mv===m));
  if(set.length!==A.atkMoves.length) continue;
  const mine=S.score(ctx,set,"all");
  const mi=ctx.mi; let tot=0,tw=0;
  for(let j=0;j<D.length;j++){ if(j===i)continue; const e=(E[j]>0&&MG[D[j].ko])?E[j]:0;
    tot+=W[j]*((1-e)*value(i,j,mi,0)+e*(e>0?value(i,j,mi,1):0)); tw+=W[j]; }
  const ref=tot/tw; maxd=Math.max(maxd,Math.abs(ref-mine));
  console.log(A.ko.padEnd(10),"추천기",mine.toFixed(5),"모델",ref.toFixed(5)); n++;
}
console.log("최대 차이",maxd.toFixed(6));
