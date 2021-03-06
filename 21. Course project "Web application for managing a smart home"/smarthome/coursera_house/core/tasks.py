from __future__ import absolute_import, unicode_literals
import requests
from celery import task
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail import send_mail
from .models import Setting


TOKEN = settings.SMART_HOME_ACCESS_TOKEN
url = settings.SMART_HOME_API_URL
headers = {"Authorization": f"Bearer {TOKEN}"}


@task()
def smart_home_manager():
    """The function polls the remote smart home server, processes the received data,
    takes managerial decisions and makes changes to the system."""
    controller_data = requests.get(url, headers=headers).json().get("data")
    controller_data = {x["name"]: x for x in controller_data}
    payload = {"controllers": []}
    if controller_data["leak_detector"]["value"]:
        # if the sensor shows a leak - we shut off hot and cold water
        if controller_data["cold_water"]["value"]:
            payload["controllers"].append({"name": "cold_water", "value": False})

        if controller_data["hot_water"]["value"]:
            payload["controllers"].append({"name": "hot_water", "value": False})
        email = EmailMessage(
            'leak detector',
            'text',
            settings.EMAIL_HOST,
            [settings.EMAIL_RECEPIENT],
        )
        email.send(fail_silently=False)


    # if there is no cold water - turn off the boiler and the washing machine
    if (
        controller_data["leak_detector"]["value"]
        or not controller_data["cold_water"]["value"]
    ):
        if controller_data["boiler"]["value"]:
            payload["controllers"].append({"name": "boiler", "value": False})
        if controller_data["washing_machine"]["value"] in ("on", "broken"):
            payload["controllers"].append({"name": "washing_machine", "value": "off"})


    boiler_temperature = controller_data["boiler_temperature"]["value"]
    hot_water_target_temperature = Setting.objects.get(
        controller_name="hot_water_target_temperature"
    ).value

    bedroom_temperature = controller_data["bedroom_temperature"]["value"]
    bedroom_target_temperature = Setting.objects.get(
        controller_name="bedroom_target_temperature"
    ).value

    if controller_data["smoke_detector"]["value"]:
        # If the smoke sensor has worked, turn off the air conditioner, boiler and light
        if controller_data["air_conditioner"]["value"]:
            payload["controllers"].append({"name": "air_conditioner", "value": False})
        if controller_data["bathroom_light"]["value"]:
            payload["controllers"].append({"name": "bathroom_light", "value": False})
        if controller_data["bedroom_light"]["value"]:
            payload["controllers"].append({"name": "bedroom_light", "value": False})
        if controller_data["boiler"]["value"]:
            payload["controllers"].append({"name": "boiler", "value": False})
        if controller_data["washing_machine"]["value"] in ("on", "broken"):
            payload["controllers"].append({"name": "washing_machine", "value": "off"})

    can_turn_on = {
        "boiler": controller_data["cold_water"]["value"]
        and not controller_data["leak_detector"]["value"]
        and not controller_data["smoke_detector"]["value"]
        and not controller_data["boiler"],
        "air_conditioner": not controller_data["smoke_detector"]["value"],
    }

    if (boiler_temperature < hot_water_target_temperature * 0.9) and can_turn_on[
        "boiler"
    ]:
        payload["controllers"].append({"name": "boiler", "value": True})

    if boiler_temperature > hot_water_target_temperature * 1.1:
        payload["controllers"].append({"name": "boiler", "value": False})

    if (bedroom_temperature < bedroom_target_temperature * 0.9) and can_turn_on[
        "air_conditioner"
    ]:
        payload["controllers"].append({"name": "air_conditioner", "value": False})

    if bedroom_temperature > bedroom_target_temperature * 1.1:
        payload["controllers"].append({"name": "air_conditioner", "value": True})

    outdoor_light = controller_data["outdoor_light"]["value"]
    bedroom_light = controller_data["bedroom_light"]["value"]

    # open and close the curtains depending on the light sensor
    if controller_data["curtains"]["value"] == "slightly_open":
        pass
    else:
        if outdoor_light < 50 and not bedroom_light:
            if controller_data["curtains"]["value"] == 'close':
                payload["controllers"].append({"name": "curtains", "value": "open"})
        elif outdoor_light > 50 or bedroom_light:
            if controller_data["curtains"]["value"] == 'open':
                payload["controllers"].append({"name": "curtains", "value": "close"})

    if payload["controllers"]:
        unique = []
        for item in payload["controllers"]:
            if item not in unique:
                unique.append(item)
        payload["controllers"] = unique
        requests.post(url, headers=headers, json=payload)