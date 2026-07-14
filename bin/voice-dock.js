(()=>{
'use strict';
let activeField=null,recognition=null,listening=false,shortcutLatched=false;
const NativeSpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
const ready=fn=>document.readyState==='loading'?document.addEventListener('DOMContentLoaded',fn):fn();
ready(()=>{
  document.addEventListener('focusin',event=>{
    if(event.target.matches?.('textarea,input[type=text],input:not([type]),[contenteditable=true]')&&!event.target.closest('.voice-dock'))activeField=event.target;
  });
  const dock=document.createElement('aside');
  dock.className='voice-dock';
  dock.setAttribute('aria-label','MyPeople Dictation');
  dock.innerHTML=`<button type="button" class="voice-dock__trigger" data-action="record" aria-label="Start dictation" aria-pressed="false" title="Dictation · Ctrl + Windows"><svg class="voice-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0M12 17v4M9 21h6"/></svg><span class="voice-meter" aria-hidden="true"><i></i><i></i><i></i></span></button><span class="voice-dock__hint" role="status" aria-live="polite">Ready · Ctrl + Windows</span>`;
  document.body.append(dock);
  const button=dock.querySelector('[data-action=record]');
  const hint=dock.querySelector('.voice-dock__hint');

  function setState(message,mode=''){
    dock.className='voice-dock'+(mode?' '+mode:'');
    hint.textContent=message;
    button.setAttribute('aria-pressed',String(mode==='listening'));
    button.setAttribute('aria-label',mode==='listening'?'Stop dictation':'Start dictation');
  }
  function fieldTarget(){
    if(activeField?.isConnected)return activeField;
    return document.querySelector('#commentInput,#taskInput,#newTask,#pcomment,textarea,input[type=text],[contenteditable=true]');
  }
  function insertIntoField(field,text){
    if(field.matches('input,textarea')){
      const start=field.selectionStart??field.value.length,end=field.selectionEnd??start;
      const lead=start&&field.value[start-1]&&!/\s/.test(field.value[start-1])?' ':'';
      field.setRangeText(lead+text,start,end,'end');
      field.dispatchEvent(new Event('input',{bubbles:true}));
      field.focus();
      return true;
    }
    if(field.isContentEditable){
      field.focus();
      const selection=getSelection();
      if(!selection?.rangeCount)return false;
      const range=selection.getRangeAt(0);
      range.deleteContents();
      range.insertNode(document.createTextNode(text));
      range.collapse(false);
      field.dispatchEvent(new Event('input',{bubbles:true}));
      return true;
    }
    return false;
  }
  async function deliverTranscript(rawText){
    const text=String(rawText||'').trim();
    if(!text)return;
    const agent=document.body.dataset.terminalAgent||'';
    try{
      if(agent){
        const response=await fetch('/voice/paste',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent,text})});
        const payload=await response.json();
        if(!response.ok)throw new Error(payload.error||'terminal_paste_failed');
      }else{
        const target=fieldTarget();
        if(!target||!insertIntoField(target,text))throw new Error('Select a text field first');
      }
      setState('Text inserted · still listening','listening');
    }catch(error){
      setState(error.message||'Could not insert text','error');
    }
  }
  function buildRecognition(){
    if(!NativeSpeechRecognition)return null;
    const engine=new NativeSpeechRecognition();
    engine.lang=document.documentElement.dataset.voiceLang||localStorage.getItem('mypeople.voiceLang')||'es-AR';
    engine.continuous=true;
    engine.interimResults=true;
    engine.maxAlternatives=1;
    engine.onstart=()=>setState('Listening…','listening');
    engine.onresult=event=>{
      let finalText='',interimText='';
      for(let index=event.resultIndex;index<event.results.length;index++){
        const segment=event.results[index][0]?.transcript||'';
        if(event.results[index].isFinal)finalText+=segment;
        else interimText+=segment;
      }
      if(interimText)setState('Listening · '+interimText.trim().slice(-44),'listening');
      if(finalText)deliverTranscript(finalText);
    };
    engine.onerror=event=>{
      listening=false;
      const message=event.error==='not-allowed'?'Microphone blocked · use Win + H':event.error==='no-speech'?'No speech detected · try again':'Dictation unavailable · '+event.error;
      setState(message,'error');
    };
    engine.onend=()=>{
      const wasListening=listening;
      listening=false;
      recognition=null;
      if(wasListening)setState('Dictation stopped · Ctrl + Windows');
    };
    return engine;
  }
  function startListening(){
    if(listening)return;
    if(!NativeSpeechRecognition){setState('Use Win + H · browser dictation unavailable','error');return;}
    recognition=buildRecognition();
    listening=true;
    setState('Opening microphone…','listening');
    try{recognition.start();}
    catch(error){listening=false;recognition=null;setState('Could not start · use Win + H','error');}
  }
  function stopListening(){
    if(!listening)return;
    listening=false;
    try{recognition?.stop();}
    catch{}
    setState('Dictation stopped · Ctrl + Windows');
  }
  function toggleListening(){listening?stopListening():startListening();}

  button.addEventListener('click',toggleListening);
  document.addEventListener('keydown',event=>{
    if(event.ctrlKey&&event.metaKey){
      if(shortcutLatched||event.repeat)return;
      shortcutLatched=true;
      event.preventDefault();
      toggleListening();
    }
  });
  document.addEventListener('keyup',event=>{if(!event.ctrlKey||!event.metaKey)shortcutLatched=false;});
  window.addEventListener('blur',()=>{shortcutLatched=false;});
});
})();