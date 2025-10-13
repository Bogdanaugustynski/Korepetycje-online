@csrf_exempt
@never_cache
def webrtc_offer(request, rez_id: int):
    keys = _keys(rez_id)
    offer_key = keys["offer"]
    answer_key = keys["answer"]
    if request.method == "POST":
        try:
            data = _parse_json_body(request)
            t, sdp = data.get("type"), data.get("sdp")
            if t != "offer" or not isinstance(sdp,str) or not sdp.startswith("v="):
                return HttpResponseBadRequest("Invalid SDP payload (type='offer')")
            cache.set(offer_key, {"type": t, "sdp": sdp}, timeout=OFFER_TTL)
            cache.delete(answer_key)
            log.info("SET_OFFER rez=%s len=%s", rez_id, len(sdp))
            return _json_no_store({"ok": True})
        except ValueError as e:
            return HttpResponseBadRequest(str(e))
        except Exception:
            log.exception("OFFER POST error rez=%s", rez_id)
            return HttpResponseBadRequest("Internal error while posting offer")
    if request.method == "GET":
        data = cache.get(offer_key)
        if not data: return _json_no_store({"error":"No offer yet"}, status=404)
        return _json_no_store(data)
    return HttpResponseBadRequest("Method not allowed")

@csrf_exempt
@never_cache
def webrtc_answer(request, rez_id: int):
    keys = _keys(rez_id)
    offer_key = keys["offer"]
    answer_key = keys["answer"]
    if request.method == "POST":
        try:
            data = _parse_json_body(request)
            t, sdp = data.get("type"), data.get("sdp")
            if t != "answer" or not isinstance(sdp,str) or not sdp.startswith("v="):
                return HttpResponseBadRequest("Invalid SDP payload (type='answer')")
            if not cache.get(offer_key):
                return HttpResponseNotFound("No offer to answer")
            cache.set(answer_key, {"type": t, "sdp": sdp}, timeout=ANSWER_TTL)
            cache.delete(offer_key)
            log.info("SET_ANSWER rez=%s len=%s", rez_id, len(sdp))
            return _json_no_store({"ok": True})
        except ValueError as e:
            return HttpResponseBadRequest(str(e))
        except Exception:
            log.exception("ANSWER POST error rez=%s", rez_id)
            return HttpResponseBadRequest("Internal error while posting answer")
    if request.method == "GET":
        data = cache.get(answer_key)
        if not data: return _json_no_store({"error":"No answer yet"}, status=404)
        return _json_no_store(data)
    return HttpResponseBadRequest("Method not allowed")

@csrf_exempt
@never_cache
def webrtc_hangup(request, rez_id: int):
    """Czyści stan po rozłączeniu (offer/answer)"""
    if request.method != "POST":
        return HttpResponseBadRequest("Method not allowed")
    offer_key, answer_key = _keys(rez_id)["offer"], _keys(rez_id)["answer"]
    cache.delete_many([offer_key, answer_key])
    log.info("HANGUP rez=%s (state cleared)", rez_id)
    return _json_no_store({"ok": True})

@csrf_exempt
@never_cache
def webrtc_debug(request, rez_id: int):
    """Podgląd stanu (debug)"""
    if request.method != "GET":
        return HttpResponseBadRequest("Method not allowed")
    offer_key, answer_key = _keys(rez_id)["offer"], _keys(rez_id)["answer"]
    offer = cache.get(offer_key); answer = cache.get(answer_key)
    data = {
        "offer": bool(offer), "answer": bool(answer),
        "offer_len": len((offer or {}).get("sdp","") or ""),
        "answer_len": len((answer or {}).get("sdp","") or ""),
        "keys": {"offer": offer_key, "answer": answer_key},
    }
    return _json_no_store(data)

@login_required
def ping_online_status(request):
    if request.method != "POST": return JsonResponse({"error": "Tylko POST"}, status=405)
    rez_id = request.POST.get("rezerwacja_id")
    if not rez_id: return JsonResponse({"error": "Brak ID rezerwacji"}, status=400)
    status, _ = OnlineStatus.objects.get_or_create(user=request.user, rezerwacja_id=rez_id)
    status.last_ping = timezone.now(); status.save()
    return _json_no_store({"status":"ok"})

@login_required
def check_online_status(request, rezerwacja_id):
    try:
      rez = Rezerwacja.objects.get(id=rezerwacja_id)
    except Rezerwacja.DoesNotExist:
      return JsonResponse({"error":"Nie znaleziono rezerwacji"}, status=404)
    if request.user == rez.uczen: other = rez.nauczyciel
    elif request.user == rez.nauczyciel: other = rez.uczen
    else:
      return JsonResponse({"error":"Brak dostępu"}, status=403)
    try:
      os = OnlineStatus.objects.get(user=other, rezerwacja_id=rezerwacja_id)
      is_online = (timezone.now() - os.last_ping).total_seconds() < 20
    except OnlineStatus.DoesNotExist:
      is_online = False
    return _json_no_store({"online": is_online})