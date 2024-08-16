import os, json, requests, runpod

import random, time
import torch
import numpy as np
from PIL import Image
import nodes
from nodes import NODE_CLASS_MAPPINGS
from nodes import load_custom_node
from comfy_extras import nodes_custom_sampler
from comfy_extras import nodes_flux
from comfy import model_management

load_custom_node("/content/ComfyUI/custom_nodes/ComfyUI-LLaVA-OneVision")
DualCLIPLoader = NODE_CLASS_MAPPINGS["DualCLIPLoader"]()
UNETLoader = NODE_CLASS_MAPPINGS["UNETLoader"]()
VAELoader = NODE_CLASS_MAPPINGS["VAELoader"]()

LoraLoader = NODE_CLASS_MAPPINGS["LoraLoader"]()
FluxGuidance = nodes_flux.NODE_CLASS_MAPPINGS["FluxGuidance"]()
RandomNoise = nodes_custom_sampler.NODE_CLASS_MAPPINGS["RandomNoise"]()
BasicGuider = nodes_custom_sampler.NODE_CLASS_MAPPINGS["BasicGuider"]()
KSamplerSelect = nodes_custom_sampler.NODE_CLASS_MAPPINGS["KSamplerSelect"]()
BasicScheduler = nodes_custom_sampler.NODE_CLASS_MAPPINGS["BasicScheduler"]()
SamplerCustomAdvanced = nodes_custom_sampler.NODE_CLASS_MAPPINGS["SamplerCustomAdvanced"]()
VAEDecode = NODE_CLASS_MAPPINGS["VAEDecode"]()
EmptyLatentImage = NODE_CLASS_MAPPINGS["EmptyLatentImage"]()
DownloadAndLoadLLaVAOneVisionModel = NODE_CLASS_MAPPINGS["DownloadAndLoadLLaVAOneVisionModel"]()
LLaVA_OneVision_Run = NODE_CLASS_MAPPINGS["LLaVA_OneVision_Run"]()
LoadImage =  NODE_CLASS_MAPPINGS["LoadImage"]()

with torch.inference_mode():
    llava_model = DownloadAndLoadLLaVAOneVisionModel.loadmodel("lmms-lab/llava-onevision-qwen2-0.5b-si", "cuda", "bf16", "sdpa")[0]
    clip = DualCLIPLoader.load_clip("t5xxl_fp16.safetensors", "clip_l.safetensors", "flux")[0]
    unet = UNETLoader.load_unet("flux1-dev.sft", "default")[0]
    vae = VAELoader.load_vae("ae.sft")[0]

def closestNumber(n, m):
    q = int(n / m)
    n1 = m * q
    if (n * m) > 0:
        n2 = m * (q + 1)
    else:
        n2 = m * (q - 1)
    if abs(n - n1) < abs(n - n2):
        return n1
    return n2

def download_file(url, save_dir='/content/ComfyUI/input'):
    os.makedirs(save_dir, exist_ok=True)
    file_name = url.split('/')[-1]
    file_path = os.path.join(save_dir, file_name)
    response = requests.get(url)
    response.raise_for_status()
    with open(file_path, 'wb') as file:
        file.write(response.content)
    return file_path

@torch.inference_mode()
def generate(input):
    values = input["input"]

    tag_image = values['input_image_check']
    tag_image = download_file(tag_image)
    final_width = values['final_width']
    tag_prompt = values['tag_prompt']
    additional_prompt = values['additional_prompt']
    tag_seed = values['tag_seed']
    tag_temp = values['tag_temp']
    tag_max_tokens = values['tag_max_tokens']

    seed = values['seed']
    steps = values['steps']
    sampler_name = values['sampler_name']
    scheduler = values['scheduler']
    guidance = values['guidance']
    lora_strength_model = values['lora_strength_model']
    lora_strength_clip = values['lora_strength_clip']
    lora_file = values['lora_file']

    # model_management.unload_all_models()
    tag_image_width, tag_image_height = Image.open(tag_image).size
    tag_image_aspect_ratio = tag_image_width / tag_image_height
    final_height = final_width / tag_image_aspect_ratio
    tag_image = LoadImage.load_image(tag_image)[0]
    if tag_seed == 0:
        random.seed(int(time.time()))
        tag_seed = random.randint(0, 18446744073709551615)
    print(tag_seed)
    positive_prompt = LLaVA_OneVision_Run.run(tag_image, llava_model, tag_prompt, tag_max_tokens, True, tag_temp, tag_seed)[0]
    positive_prompt = f"{additional_prompt} {positive_prompt}"

    if seed == 0:
        random.seed(int(time.time()))
        seed = random.randint(0, 18446744073709551615)
    print(seed)
    unet_lora, clip_lora = LoraLoader.load_lora(unet, clip, lora_file, lora_strength_model, lora_strength_clip)
    cond, pooled = clip_lora.encode_from_tokens(clip_lora.tokenize(positive_prompt), return_pooled=True)
    cond = [[cond, {"pooled_output": pooled}]]
    cond = FluxGuidance.append(cond, guidance)[0]
    noise = RandomNoise.get_noise(seed)[0]
    guider = BasicGuider.get_guider(unet_lora, cond)[0]
    sampler = KSamplerSelect.get_sampler(sampler_name)[0]
    sigmas = BasicScheduler.get_sigmas(unet_lora, scheduler, steps, 1.0)[0]
    latent_image = EmptyLatentImage.generate(closestNumber(final_width, 16), closestNumber(final_height, 16))[0]
    sample, sample_denoised = SamplerCustomAdvanced.sample(noise, guider, sampler, sigmas, latent_image)
    decoded = VAEDecode.decode(vae, sample)[0].detach()
    Image.fromarray(np.array(decoded*255, dtype=np.uint8)[0]).save("/content/onevision_flux.png")

    result = "/content/onevision_flux.png"
    try:
        notify_uri = values['notify_uri']
        del values['notify_uri']
        if(notify_uri == "notify_uri"):
            notify_uri = os.getenv('com_camenduru_notify_uri')
        notify_token = values['notify_token']
        del values['notify_token']
        if(notify_token == "notify_token"):
            notify_token = os.getenv('com_camenduru_notify_token')
        discord_id = values['discord_id']
        del values['discord_id']
        if(discord_id == "discord_id"):
            discord_id = os.getenv('com_camenduru_discord_id')
        discord_channel = values['discord_channel']
        del values['discord_channel']
        if(discord_channel == "discord_channel"):
            discord_channel = os.getenv('com_camenduru_discord_channel')
        discord_token = values['discord_token']
        del values['discord_token']
        if(discord_token == "discord_token"):
            discord_token = os.getenv('com_camenduru_discord_token')
        job_id = values['job_id']
        del values['job_id']
        default_filename = os.path.basename(result)
        with open(result, "rb") as file:
            files = {default_filename: file.read()}
        payload = {"content": f"{json.dumps(values)} <@{discord_id}>"}
        response = requests.post(
            f"https://discord.com/api/v9/channels/{discord_channel}/messages",
            data=payload,
            headers={"Authorization": f"Bot {discord_token}"},
            files=files
        )
        response.raise_for_status()
        result_url = response.json()['attachments'][0]['url']
        notify_payload = {"jobId": job_id, "result": result_url, "status": "DONE"}
        requests.post(notify_uri, data=json.dumps(notify_payload), headers={'Content-Type': 'application/json', "Authorization": notify_token})
        return {"jobId": job_id, "result": result_url, "status": "DONE"}
    except Exception as e:
        error_payload = {"jobId": job_id, "status": "FAILED"}
        try:
            requests.post(notify_uri, data=json.dumps(error_payload), headers={'Content-Type': 'application/json', "Authorization": notify_token})
        except:
            pass
        return {"jobId": job_id, "result": f"FAILED: {str(e)}", "status": "FAILED"}
    finally:
        if os.path.exists(result):
            os.remove(result)

runpod.serverless.start({"handler": generate})