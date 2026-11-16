document.querySelectorAll('svg.ch').forEach(function(svg){
  var c=JSON.parse(svg.dataset.c),t=JSON.parse(svg.dataset.t),g=svg.dataset.g.split(',').map(Number);
  var x0=g[0],x1=g[1],y0=g[2],y1=g[3],lo=g[4],hi=g[5],n=c.length,W=svg.viewBox.baseVal.width;
  var ln=svg.querySelector('.ch-x'),dot=svg.querySelector('.ch-h'),tip=svg.parentNode.querySelector('.ch-tip');
  function move(ev){
    var r=svg.getBoundingClientRect(),vx=(ev.clientX-r.left)/r.width*W;
    var i=Math.max(0,Math.min(n-1,Math.round((vx-x0)/(x1-x0)*(n-1))));
    var X=x0+i/(n-1)*(x1-x0),Y=y0+(hi-c[i])/(hi-lo)*(y1-y0);
    ln.setAttribute('x1',X);ln.setAttribute('x2',X);ln.setAttribute('y1',y0);ln.setAttribute('y2',y1);ln.setAttribute('visibility','visible');
    dot.setAttribute('cx',X);dot.setAttribute('cy',Y);dot.setAttribute('visibility','visible');
    tip.hidden=false;tip.textContent=t[i].slice(3,5)+'.'+t[i].slice(0,2)+' '+t[i].slice(6)+' ET · '+c[i];
    var px=X/W*r.width,left=Math.min(Math.max(px+8,0),r.width-tip.offsetWidth-2);
    tip.style.transform='translate('+left+'px,'+Math.max(Y/svg.viewBox.baseVal.height*r.height-26,0)+'px)';
  }
  function out(){ln.setAttribute('visibility','hidden');dot.setAttribute('visibility','hidden');tip.hidden=true;}
  svg.addEventListener('pointermove',move);svg.addEventListener('pointerdown',move);svg.addEventListener('pointerleave',out);
});
