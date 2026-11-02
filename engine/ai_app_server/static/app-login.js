document.getElementById('form').addEventListener('submit', async (e) => {
 e.preventDefault(); const btn=document.getElementById('submit'),err=document.getElementById('error');
 btn.disabled=true;err.textContent='';try{const r=await fetch('/api/app/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value})});
 if(!r.ok)throw new Error(r.status===429?'Too many attempts, try later.':'Invalid username or password.');window.location.assign('/');}
 catch(ex){err.textContent=ex.message;}finally{btn.disabled=false;}
});
