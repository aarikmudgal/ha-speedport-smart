import assert from "node:assert/strict";
import test from "node:test";
import {bindConfigurationEditor, createConfigurationEditorController, renderConfigurationEditor} from "../../custom_components/speedport_smart/frontend/configuration-editor.js";

const SETTING = {id:"telephony_phonebook_link",title:"Online phonebook",confirmation:"LINK PHONEBOOK",requires_target:true,fields:[
  {name:"username",kind:"text",minimum:1,maximum:32},
  {name:"domain",kind:"enum",choices:[{value:"0",label:"0"},{value:"1",label:"1"},{value:"2",label:"2"}]},
  {name:"password",kind:"secret",minimum:1,maximum:64},
]};
const TARGETS = [{id:"book-a",label:"Book"},{id:"book-b",label:"Book"}];
const TOKEN = "abcdef".repeat(8);
const pending = () => ({status:"pending_confirmation",pending_link:TOKEN,expires_in:120,target_id:"book-a",phonebook_id:5,online_contacts:21,local_contacts:2});
const manual = {status:"outcome_unknown",verification:"manual_required"};
const deferred = () => {let resolve;const promise=new Promise(yes=>resolve=yes);return {promise,resolve};};

async function setup({now,saveResult=pending,finishResult=()=>manual,setting=SETTING}={}) {
  const calls=[];const references=[];
  const controller=createConfigurationEditorController({now,request:async message=>{
    calls.push(structuredClone(message));references.push(message);
    if(message.type.endsWith("/targets"))return {setting_id:setting.id,targets:TARGETS};
    if(message.type.endsWith("/read"))return {setting_id:setting.id,target_id:message.target_id,revision:"revision",expires_in:120,values:{username:"old",domain:"0"}};
    return message.type.endsWith("/finish")?finishResult(message):saveResult(message);
  }});
  controller.open({entryId:"entry-a",setting});
  assert.equal(calls.length,0);
  await controller.loadTargets();controller.selectTarget("book-a");await controller.load();
  controller.setValue("username","new");controller.setValue("password","PRIVATE-PASSWORD");controller.setConfirmation(setting.confirmation);
  return {controller,calls,references};
}

test("first online link exposes counts but no token, credentials or implicit second write",async()=>{
  const {controller:c,calls}=await setup();
  assert.equal(await c.save(),true);assert.equal(calls.length,3);
  const view=c.snapshot();assert.equal(view.status,"pending_confirmation");assert.equal(view.linkPending,true);
  assert.deepEqual(view.link,{phonebookId:5,onlineContacts:21,localContacts:2,mergeExisting:null});
  assert.doesNotMatch(JSON.stringify(view),new RegExp(`${TOKEN}|PRIVATE-PASSWORD`));
  const html=renderConfigurationEditor(c);assert.doesNotMatch(html,new RegExp(`${TOKEN}|PRIVATE-PASSWORD`));
  assert.match(html,/data-setting-link-choice/);assert.match(html,/Select merge or replace/);
  assert.match(html,/data-setting-link-confirmation[^>]*disabled/);
  assert.equal(await c.finishLink(),false);assert.equal(calls.length,3);
  c.dispose();
});

for(const merge of [true,false])test(`explicit ${merge?"merge":"replace"} burns one token before awaiting`,async()=>{
  const waiting=deferred();const {controller:c,calls,references}=await setup({finishResult:()=>waiting.promise});
  await c.save();assert.equal(c.setLinkChoice(merge),true);assert.equal(calls.length,3);
  c.setLinkConfirmation(merge?"REPLACE LOCAL PHONEBOOK CONTACTS":"MERGE ONLINE PHONEBOOK CONTACTS");
  assert.equal(await c.finishLink(),false);assert.equal(calls.length,3);
  const phrase=merge?"MERGE ONLINE PHONEBOOK CONTACTS":"REPLACE LOCAL PHONEBOOK CONTACTS";
  c.setLinkConfirmation(phrase);const work=c.finishLink();
  assert.equal(c.snapshot().linkPending,false);assert.equal(c.snapshot().busy,true);
  assert.equal(await c.finishLink(),false);assert.equal(c.selectTarget("book-b"),false);
  assert.deepEqual(calls[3],{type:"speedport_smart/panel/phonebook_link/finish",entry_id:"entry-a",pending_link:TOKEN,target_id:"book-a",phonebook_id:5,merge_existing:merge,confirmed:true,confirmation_text:phrase});
  waiting.resolve(manual);assert.equal(await work,false);assert.equal(c.snapshot().status,"link_manual_required");
  assert.equal(references[3].pending_link,"");assert.equal(references[3].confirmation_text,"");
  assert.equal(await c.finishLink(),false);assert.equal(calls.length,4);
  assert.match(renderConfigurationEditor(c),/Online synchronization.*could not be independently verified/);
  c.dispose();
});

for(const malformed of [
  {pending_link:"bad"},{pending_link:"A".repeat(48)},{expires_in:0},{expires_in:121},{expires_in:"120"},
  {target_id:"book-b"},{phonebook_id:-1},{phonebook_id:6},{phonebook_id:true},{phonebook_id:"0"},
  {online_contacts:1001},{online_contacts:-1},{online_contacts:1.5},{local_contacts:NaN},{local_contacts:"2"},
])test(`malformed continuation fails closed ${JSON.stringify(malformed)}`,async()=>{
  const {controller:c,calls}=await setup({saveResult:()=>({...pending(),...malformed})});
  assert.equal(await c.save(),false);assert.equal(c.snapshot().status,"outcome_unknown");
  assert.equal(c.snapshot().linkPending,false);assert.equal(await c.finishLink(),false);assert.equal(calls.length,3);c.dispose();
});

test("another setting cannot turn an unexpected reply into a phonebook continuation",async()=>{
  const {controller:c,calls}=await setup({setting:{...SETTING,id:"other_setting"}});
  assert.equal(await c.save(),false);assert.equal(await c.finishLink(),false);assert.equal(calls.length,3);c.dispose();
});

test("expired continuation clears without another request",async()=>{
  let clock=0;const {controller:c,calls}=await setup({now:()=>clock});await c.save();
  c.setLinkChoice(true);c.setLinkConfirmation("MERGE ONLINE PHONEBOOK CONTACTS");clock=120000;
  assert.equal(await c.finishLink(),false);assert.equal(c.snapshot().status,"link_expired");
  assert.equal(c.snapshot().linkPending,false);assert.equal(calls.length,3);c.dispose();
});

test("expiry timer forgets approval without polling or router I/O",async(t)=>{
  const timers=[];t.mock.method(globalThis,"setTimeout",(callback,delay)=>{timers.push({callback,delay});return {unref(){}};});
  t.mock.method(globalThis,"clearTimeout",()=>{});
  const {controller:c,calls}=await setup();await c.save();assert.equal(timers.length,1);assert.equal(timers[0].delay,120000);
  timers[0].callback();assert.equal(c.snapshot().status,"link_expired");assert.equal(c.snapshot().linkPending,false);
  assert.equal(calls.length,3);assert.equal(await c.finishLink(),false);c.dispose();
});

for(const reset of ["close","dispose","load","loadTargets","target","router","user"])test(`${reset} clears pending continuation and private confirmation`,async()=>{
  const {controller:c,calls}=await setup();await c.save();c.setLinkChoice(true);c.setLinkConfirmation("MERGE ONLINE PHONEBOOK CONTACTS");
  if(reset==="target")c.selectTarget("book-b");
  else if(reset==="router"||reset==="user")c.open({entryId:reset==="router"?"entry-b":"entry-a",setting:SETTING});
  else await c[reset]();
  assert.equal(c.snapshot()?.linkPending??false,false);assert.equal(await c.finishLink(),false);
  assert.equal(calls.filter(message=>message.type.endsWith("/finish")).length,0);c.dispose();
});

test("late first-stage response cannot attach approval to a new router",async()=>{
  const waiting=deferred();const {controller:c,calls}=await setup({saveResult:()=>waiting.promise});
  const work=c.save();c.open({entryId:"entry-b",setting:SETTING});waiting.resolve(pending());
  assert.equal(await work,false);assert.equal(c.snapshot().entryId,"entry-b");assert.equal(c.snapshot().linkPending,false);
  assert.equal(await c.finishLink(),false);assert.equal(calls.length,3);c.dispose();
});

test("late finish response cannot update replacement editor and cannot replay",async()=>{
  const waiting=deferred();const {controller:c,calls}=await setup({finishResult:()=>waiting.promise});await c.save();
  c.setLinkChoice(false);c.setLinkConfirmation("REPLACE LOCAL PHONEBOOK CONTACTS");const work=c.finishLink();
  c.open({entryId:"entry-b",setting:SETTING});waiting.resolve(manual);await work;
  assert.equal(c.snapshot().status,"target_required");assert.equal(await c.finishLink(),false);assert.equal(calls.length,4);c.dispose();
});

test("finish errors never expose credentials, claim success or retry",async()=>{
  const {controller:c,calls}=await setup({finishResult:()=>{throw new Error("PRIVATE-PASSWORD");}});await c.save();
  c.setLinkChoice(true);c.setLinkConfirmation("MERGE ONLINE PHONEBOOK CONTACTS");assert.equal(await c.finishLink(),false);
  assert.equal(c.snapshot().status,"outcome_unknown");assert.doesNotMatch(renderConfigurationEditor(c),/PRIVATE-PASSWORD/);
  assert.equal(await c.finishLink(),false);assert.equal(calls.length,4);c.dispose();
});

test("rerender clears hidden second confirmation and binding cleanup clears DOM",async()=>{
  const {controller:c,calls}=await setup();await c.save();c.setLinkChoice(true);c.setLinkConfirmation("MERGE ONLINE PHONEBOOK CONTACTS");
  renderConfigurationEditor(c);assert.equal(await c.finishLink(),false);assert.equal(calls.length,3);
  const listeners=new Map();const input={value:"PRIVATE"};let selector;
  const root={contains:()=>true,addEventListener:(key,fn)=>listeners.set(key,fn),removeEventListener:key=>listeners.delete(key),querySelectorAll:value=>{selector=value;return[input];}};
  const dispose=bindConfigurationEditor(root,c);dispose();assert.match(selector,/data-setting-link-confirmation/);
  assert.equal(input.value,"");assert.equal(c.snapshot(),null);assert.equal(listeners.size,0);
});

test("time fields load and save exact 24:00 through a text control",async()=>{
  const setting={id:"schedule",confirmation:"SAVE SETTINGS",fields:[{name:"end",kind:"time"}]};const calls=[];
  const c=createConfigurationEditorController({request:async message=>{calls.push(structuredClone(message));return message.type.endsWith("/read")?{setting_id:"schedule",revision:"r",expires_in:120,values:{end:"24:00"}}:{status:"verified"};}});
  c.open({entryId:"entry",setting});assert.equal(await c.load(),true);
  const html=renderConfigurationEditor(c);assert.match(html,/type="text"[^>]*data-setting-field="end"[^>]*inputmode="numeric"/);assert.match(html,/value="24:00"/);
  c.setValue("end","23:59");c.setConfirmation("SAVE SETTINGS");assert.equal(await c.save(),true);
  assert.equal(calls[1].changes.end,"23:59");c.dispose();
  const d=createConfigurationEditorController({request:async message=>message.type.endsWith("/read")?{setting_id:"schedule",revision:"r",expires_in:120,values:{end:"23:59"}}:{status:"verified"}});
  d.open({entryId:"entry",setting});await d.load();d.setValue("end","24:00");d.setConfirmation("SAVE SETTINGS");assert.equal(await d.save(),true);d.dispose();
});

for(const value of ["24:01","24:59","25:00","00:60","1:00","24:0"])test(`invalid time ${value} never sends save`,async()=>{
  let calls=0;const c=createConfigurationEditorController({request:async()=>{calls++;return{setting_id:"schedule",revision:"r",expires_in:120,values:{end:"23:59"}};}});
  c.open({entryId:"entry",setting:{id:"schedule",confirmation:"SAVE SETTINGS",fields:[{name:"end",kind:"time"}]}});await c.load();
  c.setValue("end",value);c.setConfirmation("SAVE SETTINGS");assert.equal(await c.save(),false);assert.equal(calls,1);c.dispose();
});
