import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {PRIVATE_COMMAND_TYPES,requestPrivateApi} from "../../custom_components/speedport_smart/frontend/private-api.js";
import {createConfigurationEditorController} from "../../custom_components/speedport_smart/frontend/configuration-editor.js";

const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{"content-type":"application/json"}});
const command=(type="speedport_smart/panel/settings/save")=>({type,entry_id:"entry-a",changes:{password:"PRIVATE-PASSWORD"},revision:"PRIVATE-REVISION",confirmed:true,confirmation_text:"SAVE SETTINGS"});
const fixture=(send=()=>json({result:{status:"verified"}}))=>{
  const calls=[];const options=[];const hass={user:{id:"admin",is_admin:true},fetchWithAuth:async(path,init)=>{calls.push([path,structuredClone(init)]);options.push(init);return send(path,init);},callWS:()=>assert.fail("no WS"),connection:{sendMessagePromise:()=>assert.fail("no WS")}};
  return {hass,calls,options};
};

test("one private POST keeps all credentials out of URL and clears temporary body",async()=>{
  const {hass,calls,options}=fixture();const input=command();
  assert.deepEqual(await requestPrivateApi(hass,input),{status:"verified"});assert.equal(calls.length,1);
  assert.equal(calls[0][0],"/api/speedport_smart/private/entry-a");assert.doesNotMatch(calls[0][0],/PRIVATE|\?/);
  assert.deepEqual(calls[0][1],{method:"POST",headers:{"Content-Type":"application/json",Accept:"application/json"},body:JSON.stringify(input),cache:"no-store",redirect:"error"});
  assert.equal(options[0].body,"");assert.equal(input.changes.password,"PRIVATE-PASSWORD");
});

test("every private command uses the same closed endpoint without metadata or arbitrary proxy",async()=>{
  assert.equal(PRIVATE_COMMAND_TYPES.length,31);assert.equal(new Set(PRIVATE_COMMAND_TYPES).size,31);
  assert.ok(PRIVATE_COMMAND_TYPES.includes("speedport_smart/panel/ip_information"));
  assert.ok(PRIVATE_COMMAND_TYPES.includes("speedport_smart/panel/admin_read"));
  for(const type of PRIVATE_COMMAND_TYPES){const {hass,calls}=fixture();await requestPrivateApi(hass,{type,entry_id:"entry-a"});assert.equal(calls.length,1);}
  for(const type of ["speedport_smart/panel","other/panel/settings/save","speedport_smart/panel/settings/unknown","https://router.invalid"]){
    const {hass,calls}=fixture();await assert.rejects(requestPrivateApi(hass,{type,entry_id:"entry-a"}),{code:"invalid_input"});assert.equal(calls.length,0);
  }
});

test("relative authenticated route works with HTTP and HTTPS HA origins",async()=>{
  for(const origin of ["http://ha.invalid:8123","https://ha.invalid"]){
    const {hass}=fixture(path=>{assert.equal(new URL(path,origin).origin,origin);return json({result:{}});});await requestPrivateApi(hass,command());
  }
});

test("non-admin, missing authenticated fetch and unsafe entry IDs never dispatch",async()=>{
  for(const user of [null,{id:"u",is_admin:false},{is_admin:true}]){const {hass,calls}=fixture();hass.user=user;await assert.rejects(requestPrivateApi(hass,command()),{code:"administrator_required"});assert.equal(calls.length,0);}
  for(const entry_id of ["../other","entry?password=secret","entry/other","",null,"e".repeat(65)]){const {hass,calls}=fixture();await assert.rejects(requestPrivateApi(hass,{...command(),entry_id}),{code:"invalid_input"});assert.equal(calls.length,0);}
  const {hass,calls}=fixture();delete hass.fetchWithAuth;await assert.rejects(requestPrivateApi(hass,command()),{code:"invalid_input"});assert.equal(calls.length,0);
});

test("WS IDs, serialization redirects and oversized UTF-8 requests fail before dispatch",async()=>{
  const cyclic=command();cyclic.self=cyclic;
  for(const input of [{...command(),id:1},{...command(),toJSON:()=>({type:"other",entry_id:"entry-a"})},{...command(),changes:{password:"é".repeat(140000)}},cyclic]){
    const {hass,calls}=fixture();await assert.rejects(requestPrivateApi(hass,input),error=>{assert.doesNotMatch(String(error),/PRIVATE|circular|password/);return true;});assert.equal(calls.length,0);
  }
});

test("known error codes preserved, all server messages and unknown codes discarded",async()=>{
  for(const code of ["stale_settings","action_rejected","administrator_required","bonding_managed_by_easy_support","settings_prerequisites_unavailable","settings_unavailable","usb_disabled","tethering_unavailable_with_receiver","system_mesh_unavailable","system_mesh_local_update_only","system_firmware_managed_automatically","system_firmware_offer_unavailable","vpn_key_rotation_unavailable","system_smarthome_unavailable","call_history_unavailable","PRIVATE-PASSWORD"]){
    const {hass,calls}=fixture(()=>json({error:{code,message:"PRIVATE-SSID PRIVATE-PASSWORD"}},400));
    await assert.rejects(requestPrivateApi(hass,command()),error=>{assert.equal(error.code,code==="PRIVATE-PASSWORD"?"private_transport_failed":code);assert.doesNotMatch(String(error),/PRIVATE|SSID/);return true;});assert.equal(calls.length,1);
  }
});

test("transport failure sends exactly once with no WS fallback",async()=>{
  const {hass,calls,options}=fixture(()=>{throw new Error("PRIVATE-PASSWORD");});
  await assert.rejects(requestPrivateApi(hass,command()),error=>{assert.equal(error.code,"private_transport_failed");assert.doesNotMatch(String(error),/PRIVATE/);return true;});
  assert.equal(calls.length,1);assert.equal(options[0].body,"");
});

test("malformed and redirected responses cannot be mistaken for success",async()=>{
  const redirected=json({result:{status:"verified"}});Object.defineProperty(redirected,"redirected",{value:true});
  for(const response of [new Response("PRIVATE HTML",{headers:{"content-type":"text/html"}}),json({error:{code:"invalid_input"}}),json({result:{},error:{}}),json([]),json({}),new Response("PRIVATE invalid",{headers:{"content-type":"application/json"}}),redirected]){
    const {hass,calls}=fixture(()=>response);await assert.rejects(requestPrivateApi(hass,command()),{code:"private_transport_failed"});assert.equal(calls.length,1);
  }
});

test("bounded chunked responses reject oversize, bad UTF-8 and length mismatch",async()=>{
  let cancelled=false;
  const stream=new ReadableStream({start(controller){controller.enqueue(new Uint8Array(32*1024*1024+1));},cancel(){cancelled=true;}});
  const responses=[new Response(stream,{headers:{"content-type":"application/json"}}),
    new Response(new Uint8Array([255]),{headers:{"content-type":"application/json"}}),
    new Response('{"result":{}}',{headers:{"content-type":"application/json","content-length":"1"}}),
    new Response("",{headers:{"content-type":"application/json","content-length":String(32*1024*1024+1)}})];
  for(const response of responses){const {hass}=fixture(()=>response);await assert.rejects(requestPrivateApi(hass,command()),{code:"private_transport_failed"});}
  assert.equal(cancelled,true);
});

test("large valid private UTF-8 export and transparently decoded response stay usable",async()=>{
  const content="😀".repeat(2100000);
  const {hass}=fixture(()=>json({result:{content}}));
  assert.equal((await requestPrivateApi(hass,command())).content,content);
  const decoded=new Response('{"result":{"status":"verified"}}',{headers:{"content-type":"application/json","content-length":"12","content-encoding":"gzip"}});
  const other=fixture(()=>decoded);assert.deepEqual(await requestPrivateApi(other.hass,command()),{status:"verified"});
});

test("revocation during private read withholds its payload",async()=>{
  const {hass,calls}=fixture(()=>{hass.user={id:"other",is_admin:true};return json({result:{password:"PRIVATE"}});});
  await assert.rejects(requestPrivateApi(hass,command()),{code:"administrator_required"});assert.equal(calls.length,1);
});

test("settings controller uses HTTP for one read and one explicit secret save",async()=>{
  const setting={id:"test_setting",confirmation:"SAVE SETTINGS",fields:[{name:"password",kind:"secret",minimum:1}]};
  const {hass,calls}=fixture((_path,init)=>{const input=JSON.parse(init.body);return json({result:input.type.endsWith("/read")?{setting_id:setting.id,revision:"revision",expires_in:120,values:{}}:{status:"secret_unverified"}});});
  const c=createConfigurationEditorController({request:message=>requestPrivateApi(hass,message)});c.open({entryId:"entry-a",setting});assert.equal(calls.length,0);
  await c.load();c.setValue("password","PRIVATE-PASSWORD");c.setConfirmation("SAVE SETTINGS");assert.equal(await c.save(),true);assert.equal(calls.length,2);
  assert.equal(JSON.parse(calls[1][1].body).changes.password,"PRIVATE-PASSWORD");assert.doesNotMatch(JSON.stringify(c.snapshot()),/PRIVATE-PASSWORD/);assert.equal(await c.save(),false);c.dispose();
});

test("transport has no credential storage, WS call, logging or retry loop",()=>{
  const source=readFileSync(new URL("../../custom_components/speedport_smart/frontend/private-api.js",import.meta.url),"utf8");
  assert.doesNotMatch(source,/localStorage|sessionStorage|console\.|callWS\(|sendMessagePromise\(|setTimeout\(|setInterval\(/);
  assert.equal((source.match(/await hass\.fetchWithAuth\(/g)||[]).length,1);
});
