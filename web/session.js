'use strict';
let currentUser=null;
let supabaseClient=null;
let authReady=false;
let initializing=null;
let pendingFactorId=null;
let pendingEnrollment=null;
let verifiedFactorId=null;
let recoveryMode=location.hash==='#reset-password'&&new URLSearchParams(location.search).has('code');
let authMode=location.hash==='#create-account'?'signup':'signin';

function setAuthControls(enabled){
  const form=$('#login-form');
  form.querySelectorAll('input,button').forEach(element=>element.disabled=!enabled);
  form.elements.name.disabled=!enabled||authMode!=='signup';
  form.elements.confirmPassword.disabled=!enabled||authMode!=='signup';
  $('#forgot-password').disabled=!enabled||authMode!=='signin';
}
function setAuthStatus(message,state='ready'){
  const status=$('#auth-status');
  status.dataset.state=state;
  status.querySelector('span').textContent=message;
}
function setLoginMessage(message='',state='error'){
  const target=$('#login-error');
  target.textContent=message;
  target.dataset.state=message?state:'';
}
function setAuthMode(mode,{focus=true,preserveMessage=false,updateLocation=false}={}){
  const nextMode=mode==='signup'?'signup':'signin';
  const form=$('#login-form');
  const modeChanged=authMode!==nextMode;
  authMode=nextMode;
  form.dataset.mode=authMode;
  form.querySelectorAll('[data-auth-mode]').forEach(button=>{
    const selected=button.dataset.authMode===authMode;
    button.setAttribute('aria-selected',String(selected));
    button.tabIndex=selected?0:-1;
  });
  const creating=authMode==='signup';
  $('#auth-name-field').hidden=!creating;
  $('#auth-confirm-field').hidden=!creating;
  $('#password-guidance').hidden=!creating;
  $('#forgot-password').hidden=creating;
  form.elements.name.required=creating;
  form.elements.confirmPassword.required=creating;
  form.elements.password.autocomplete=creating?'new-password':'current-password';
  form.elements.password.minLength=creating?12:1;
  $('#login-title').textContent=creating?'Create your TenderDesk account.':'Welcome back.';
  $('#login-copy').textContent=creating?'Use your work email to create a private procurement workspace.':'Sign in to review saved opportunities and recommendations.';
  $('#auth-submit-label').textContent=creating?'Create account':'Sign in';
  if(modeChanged){
    form.elements.password.value='';
    form.elements.confirmPassword.value='';
  }
  if(!preserveMessage)setLoginMessage('');
  setAuthControls(authReady);
  if(updateLocation)history.replaceState(null,'',location.pathname+location.search+(creating?'#create-account':''));
  if(focus)(creating?form.elements.name:form.elements.email).focus();
}
function selectAuthScreen(name){
  $('#login-screen').hidden=false;
  $('#login-form').hidden=name!=='login';
  $('#recovery-form').hidden=name!=='recovery';
  $('#mfa-form').hidden=name!=='mfa';
}
function clearWorkspace(){
  const dialog=$('#detail-dialog');
  if(dialog.open)dialog.close();
  detailId=null;
  data={items:[],total:0};
  $('#notices').innerHTML='';
  $('#recommendations').innerHTML='';
}
function showLogin(message=''){
  currentUser=null;
  pendingFactorId=null;
  document.body.classList.add('signed-out');
  selectAuthScreen('login');
  setAuthMode(location.hash==='#create-account'?'signup':'signin',{focus:false,preserveMessage:true});
  setAuthControls(authReady);
  setAuthStatus(authReady?'Secure connection ready':'Secure connection unavailable',authReady?'ready':'error');
  setLoginMessage(message);
  clearWorkspace();
}
function showRecovery(){
  currentUser=null;
  document.body.classList.add('signed-out');
  selectAuthScreen('recovery');
  $('#recovery-error').textContent='';
  clearWorkspace();
  $('#recovery-form [name=password]').focus();
}
function showMfa(factorId){
  currentUser=null;
  pendingFactorId=factorId;
  document.body.classList.add('signed-out');
  selectAuthScreen('mfa');
  $('#mfa-error').textContent='';
  $('#mfa-form').reset();
  clearWorkspace();
  $('#mfa-form [name=code]').focus();
}
function authRedirect(hash){
  return location.origin+location.pathname+'#'+hash;
}
function authError(error,fallback='Authentication could not be completed.'){
  const code=error?.code||'';
  if(code==='invalid_credentials'||/invalid login credentials/i.test(error?.message||''))return 'The email or password is incorrect.';
  if(code==='email_not_confirmed')return 'Confirm your email address before signing in.';
  if(code==='over_request_rate_limit')return 'Too many attempts. Wait a moment and try again.';
  if(code==='weak_password')return 'Choose a stronger password with at least 12 characters.';
  if(code.startsWith('mfa_'))return 'The authenticator code could not be verified. Check the current code and try again.';
  return fallback;
}

async function configureAuth(){
  setAuthControls(false);
  const response=await fetch('/api/config',{headers:{Accept:'application/json'}});
  const config=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(config.error||'Supabase is not configured.');
  const endpoint=new URL(config.url);
  if(endpoint.protocol!=='https:'&&!['localhost','127.0.0.1'].includes(endpoint.hostname))throw Error('Supabase must use a secure URL.');
  if(typeof config.key!=='string'||config.key.length<20)throw Error('The Supabase publishable key is invalid.');
  const {createClient}=await import('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.102.0/+esm');
  supabaseClient=createClient(endpoint.href.replace(/\/$/,''),config.key,{auth:{
    persistSession:true,autoRefreshToken:true,detectSessionInUrl:true,flowType:'pkce'
  }});
  window.tenderdeskAccessToken=async()=>{
    if(!supabaseClient)return null;
    const {data,error}=await supabaseClient.auth.getSession();
    return error?null:data.session?.access_token||null;
  };
  supabaseClient.auth.onAuthStateChange((event)=>{
    if(event==='PASSWORD_RECOVERY'){
      recoveryMode=true;
      setTimeout(showRecovery,0);
    }else if(event==='SIGNED_OUT'){
      recoveryMode=false;
      setTimeout(()=>showLogin(),0);
    }else if(event==='SIGNED_IN'&&!currentUser&&!recoveryMode){
      setTimeout(()=>initializeSession(),0);
    }
  });
  authReady=true;
  setAuthControls(true);
  setAuthStatus('Secure connection ready','ready');
}

async function requireSecondFactor(){
  const assurance=await supabaseClient.auth.mfa.getAuthenticatorAssuranceLevel();
  if(assurance.error)throw assurance.error;
  if(assurance.data.currentLevel==='aal1'&&assurance.data.nextLevel==='aal2'){
    const factors=await supabaseClient.auth.mfa.listFactors();
    if(factors.error)throw factors.error;
    const factor=(factors.data.totp||[]).find(item=>item.status==='verified');
    if(!factor)throw Error('A verified authenticator factor was not found.');
    showMfa(factor.id);
    return true;
  }
  return false;
}

async function loadRecommendations(){
  if(!currentUser)return;
  try{
    const result=await api('/api/notices?recommended=1&sort=closing');
    if(!currentUser)return;
    $('#recommendations').innerHTML=result.items.length?'<p>'+num(result.total)+' matching open opportunities · showing up to 12</p><div class="cards-grid">'+result.items.map(n=>`<article class="notice-card">${sourceBadge(n.feed)}<button class="notice-title" data-detail="${esc(n.id)}">${esc(n.title)}</button><p class="notice-ref">${esc(n.reference)}</p>${deadline(n)}<p class="match-reason">Matches: ${(n.match_terms||[]).map(esc).join(', ')}</p></article>`).join('')+'</div>':'<div class="empty-state"><strong>No open matches in the collected archive yet.</strong>Choose more domains or add keywords. You can still browse all opportunities below; new matches appear as collection continues.</div>';
  }catch(error){if(currentUser)$('#recommendations').textContent=error.message;}
}

async function initializeSession(){
  if(initializing)return initializing;
  initializing=(async()=>{
    if(!authReady||!supabaseClient){showLogin('Authentication is not ready. Reload the page and try again.');return false;}
    try{
      const {data:{session},error}=await supabaseClient.auth.getSession();
      if(error)throw error;
      if(!session){showLogin();return false;}
      if(recoveryMode){showRecovery();return false;}
      if(await requireSecondFactor())return false;
      const result=await api('/api/me');
      currentUser=result.user;
      document.body.classList.remove('signed-out');
      $('#login-screen').hidden=true;
      setLoginMessage('');
      const name=currentUser.name||currentUser.email?.split('@')[0]||'TenderDesk user';
      const initials=name.split(/\s+/).filter(Boolean).slice(0,2).map(part=>part[0]).join('').toUpperCase()||'TD';
      $('#welcome-user').textContent='WELCOME, '+name.toUpperCase();
      $('#top-avatar').textContent=initials;
      $('#sidebar-avatar').textContent=initials;
      $('#sidebar-user').textContent=name;
      $('#sidebar-email').textContent=currentUser.email||'Supabase account';
      $('#domain-options').innerHTML=Object.keys(result.domains).map(domain=>`<label><input type="checkbox" name="domain" value="${esc(domain)}" ${(currentUser.interests||[]).includes(domain)?'checked':''}>${esc(domain==='it'?'IT & technology':domain[0].toUpperCase()+domain.slice(1))}</label>`).join('');
      $('#interests-form [name=keywords]').value=currentUser.keywords||'';
      route();
      await Promise.all([refreshDashboard(),loadRecommendations(),updateMfaStatus()]);
      return true;
    }catch(error){
      showLogin(authError(error,'Unable to verify your secure session. Sign in again.'));
      return false;
    }
  })();
  try{return await initializing;}finally{initializing=null;}
}

$('#login-form').querySelectorAll('[data-auth-mode]').forEach(button=>{
  button.onclick=()=>setAuthMode(button.dataset.authMode,{updateLocation:true});
  button.onkeydown=event=>{
    if(!['ArrowLeft','ArrowRight'].includes(event.key))return;
    event.preventDefault();
    setAuthMode(button.dataset.authMode==='signin'?'signup':'signin',{updateLocation:true});
  };
});

$('#login-form').onsubmit=async event=>{
  event.preventDefault();
  if(!authReady||!supabaseClient){showLogin('Secure authentication is still connecting.');return;}
  const button=event.target.querySelector('button[type=submit]');
  const submitLabel=$('#auth-submit-label');
  button.disabled=true;
  button.setAttribute('aria-busy','true');
  submitLabel.textContent=authMode==='signup'?'Creating account…':'Signing in…';
  setLoginMessage('');
  try{
    const form=new FormData(event.target);
    const email=String(form.get('email')).trim();
    const password=String(form.get('password'));
    if(authMode==='signup'){
      const name=String(form.get('name')).trim();
      const confirmation=String(form.get('confirmPassword'));
      if(!name){setLoginMessage('Enter your full name.');event.target.elements.name.focus();return;}
      if(password.length<12){setLoginMessage('Use at least 12 characters for your password.');event.target.elements.password.focus();return;}
      if(password!==confirmation){setLoginMessage('The passwords do not match.');event.target.elements.confirmPassword.focus();return;}
      const {data,error}=await supabaseClient.auth.signUp({email,password,options:{
        emailRedirectTo:authRedirect('overview'),data:{name}
      }});
      if(error)throw error;
      event.target.elements.password.value='';
      event.target.elements.confirmPassword.value='';
      if(data.session){
        location.hash='overview';
        if(await initializeSession())event.target.reset();
      }else{
        setAuthMode('signin',{focus:false,preserveMessage:true,updateLocation:true});
        event.target.elements.email.value=email;
        setLoginMessage('Account created. Check your email to confirm it, then sign in.','success');
        event.target.elements.email.focus();
      }
    }else{
      const {error}=await supabaseClient.auth.signInWithPassword({email,password});
      if(error)throw error;
      location.hash='overview';
      if(await initializeSession())event.target.reset();
    }
  }catch(error){setLoginMessage(authError(error,authMode==='signup'?'The account could not be created. Try again shortly.':'Authentication could not be completed.'));}
  finally{
    button.disabled=false;
    button.removeAttribute('aria-busy');
    submitLabel.textContent=authMode==='signup'?'Create account':'Sign in';
  }
};

$('#forgot-password').onclick=async()=>{
  if(!authReady||!supabaseClient)return;
  const email=$('#login-form [name=email]').value.trim();
  if(!email){setLoginMessage('Enter your email address first.');$('#login-form [name=email]').focus();return;}
  const button=$('#forgot-password');button.disabled=true;
  try{
    const {error}=await supabaseClient.auth.resetPasswordForEmail(email,{redirectTo:authRedirect('reset-password')});
    if(error)throw error;
    setLoginMessage('If an account exists for that email, a secure reset link is on its way.','success');
  }catch(error){setLoginMessage(authError(error,'The reset email could not be sent. Try again shortly.'));}
  finally{button.disabled=false;}
};

$('#recovery-form').onsubmit=async event=>{
  event.preventDefault();
  const form=new FormData(event.target);
  const password=String(form.get('password'));
  const confirmation=String(form.get('confirm_password'));
  const message=$('#recovery-error');message.textContent='';
  if(password.length<12){message.textContent='Use at least 12 characters.';return;}
  if(password!==confirmation){message.textContent='The passwords do not match.';return;}
  const button=event.target.querySelector('button[type=submit]');button.disabled=true;
  try{
    const {error}=await supabaseClient.auth.updateUser({password});
    if(error)throw error;
    recoveryMode=false;
    history.replaceState(null,'',location.pathname+'#overview');
    await supabaseClient.auth.signOut();
    setTimeout(()=>{
      showLogin('Password updated. Sign in with your new password.');
      setLoginMessage('Password updated. Sign in with your new password.','success');
    },0);
  }catch(error){message.textContent=authError(error,'Your password could not be updated. Request a new reset link.');}
  finally{button.disabled=false;}
};

$('#mfa-form').onsubmit=async event=>{
  event.preventDefault();
  const code=String(new FormData(event.target).get('code')).replace(/\D/g,'');
  const button=event.target.querySelector('button[type=submit]');button.disabled=true;$('#mfa-error').textContent='';
  try{
    if(!pendingFactorId||code.length!==6)throw Error('Enter the six-digit code from your authenticator app.');
    const challenge=await supabaseClient.auth.mfa.challenge({factorId:pendingFactorId});
    if(challenge.error)throw challenge.error;
    const verification=await supabaseClient.auth.mfa.verify({factorId:pendingFactorId,challengeId:challenge.data.id,code});
    if(verification.error)throw verification.error;
    pendingFactorId=null;
    await initializeSession();
  }catch(error){$('#mfa-error').textContent=authError(error,error.message||'The code could not be verified.');}
  finally{button.disabled=false;}
};

$('#cancel-mfa').onclick=async()=>{if(supabaseClient)await supabaseClient.auth.signOut();showLogin();};
$('#logout').onclick=async()=>{if(supabaseClient)await supabaseClient.auth.signOut({scope:'local'});showLogin();location.hash='overview';};

async function updateMfaStatus(){
  const status=$('#mfa-status'),button=$('#mfa-enroll');
  if(!supabaseClient||!currentUser){button.disabled=true;return;}
  try{
    const factors=await supabaseClient.auth.mfa.listFactors();
    if(factors.error)throw factors.error;
    const verified=(factors.data.totp||[]).find(item=>item.status==='verified');
    verifiedFactorId=verified?.id||null;
    status.textContent=verified?'Authenticator verification is enabled for this account.':'Add an authenticator app to protect your account if your password is compromised.';
    button.textContent=verified?'Remove authenticator app':'Set up authenticator app';
    button.disabled=false;
  }catch(error){status.textContent='Account security status is unavailable.';button.disabled=true;}
}

$('#mfa-enroll').onclick=async()=>{
  const button=$('#mfa-enroll');button.disabled=true;$('#mfa-settings-error').textContent='';
  try{
    if(verifiedFactorId){
      if(!confirm('Remove authenticator verification from this account?'))return;
      const result=await supabaseClient.auth.mfa.unenroll({factorId:verifiedFactorId});
      if(result.error)throw result.error;
      verifiedFactorId=null;
      $('#mfa-setup').hidden=true;
      toast('Authenticator verification removed.');
      await updateMfaStatus();
      return;
    }
    const listed=await supabaseClient.auth.mfa.listFactors();
    if(listed.error)throw listed.error;
    for(const factor of (listed.data.totp||[]).filter(item=>item.status!=='verified')){
      const removed=await supabaseClient.auth.mfa.unenroll({factorId:factor.id});
      if(removed.error)throw removed.error;
    }
    const enrollment=await supabaseClient.auth.mfa.enroll({factorType:'totp',friendlyName:'TenderDesk'});
    if(enrollment.error)throw enrollment.error;
    pendingEnrollment=enrollment.data;
    $('#mfa-qr').src=enrollment.data.totp.qr_code;
    $('#mfa-secret').textContent=enrollment.data.totp.secret;
    $('#mfa-enroll-code').value='';
    $('#mfa-setup').hidden=false;
    $('#mfa-enroll-code').focus();
  }catch(error){$('#mfa-settings-error').textContent=authError(error,'Authenticator setup could not be started.');}
  finally{button.disabled=false;}
};

$('#mfa-confirm').onclick=async()=>{
  const code=$('#mfa-enroll-code').value.replace(/\D/g,'');
  const button=$('#mfa-confirm');button.disabled=true;$('#mfa-settings-error').textContent='';
  try{
    if(!pendingEnrollment||code.length!==6)throw Error('Enter the current six-digit code.');
    const challenge=await supabaseClient.auth.mfa.challenge({factorId:pendingEnrollment.id});
    if(challenge.error)throw challenge.error;
    const verification=await supabaseClient.auth.mfa.verify({factorId:pendingEnrollment.id,challengeId:challenge.data.id,code});
    if(verification.error)throw verification.error;
    pendingEnrollment=null;
    $('#mfa-setup').hidden=true;
    toast('Two-step verification is now enabled.');
    await updateMfaStatus();
  }catch(error){$('#mfa-settings-error').textContent=authError(error,error.message||'The code could not be verified.');}
  finally{button.disabled=false;}
};

$('#interests-form').onsubmit=async event=>{
  event.preventDefault();
  const button=event.target.querySelector('button');button.disabled=true;
  try{
    const values=new FormData(event.target);
    await api('/api/profile',{interests:values.getAll('domain'),keywords:values.get('keywords')});
    await initializeSession();
    toast('Your interests and recommendations are updated.');
  }catch(error){toast(error.message);}
  finally{button.disabled=false;}
};

configureAuth().then(initializeSession).catch(error=>{
  authReady=false;
  showLogin('Authentication is unavailable: '+error.message);
  setAuthControls(false);
});
