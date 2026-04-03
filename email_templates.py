import json

# Shared styling and layout components to keep the templates consistent and modern.
_LOGO_URL = "https://test-brain.netlify.app/assets/club-logo.webp"
_BG_COLOR = "#000101"
_CARD_BG = "#0a1628"
_ACCENT = "#3ed2ff"
_ACCENT_DARK = "#198acd"
_TEXT_COLOR = "#e6f7ff"
_MUTED = "#7fa6bd"
_RED_ACCENT = "#f87171"

def _wrap_html(content, title, subtitle):
    """Wraps the specific template content into the common dark-themed layout."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background-color:{_BG_COLOR};font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color:{_BG_COLOR};padding:40px 16px;">
<tr><td align="center">

<table width="600" cellpadding="0" cellspacing="0" 
       style="background-color:{_CARD_BG};border:1px solid rgba(25,138,205,0.3);border-radius:24px;overflow:hidden;box-shadow:0 0 60px rgba(62,210,255,0.08);">
  
  <!-- Header -->
  <tr><td style="padding:48px 40px 32px;text-align:center;">
    <img src="{_LOGO_URL}" width="80" height="80" 
         style="display:block;margin:0 auto 20px;border-radius:50%;border:2px solid {_ACCENT_DARK};box-shadow:0 0 20px rgba(25,138,205,0.5);"/>
    <h1 style="margin:0;color:{_TEXT_COLOR};font-size:28px;font-weight:900;letter-spacing:1px;text-transform:uppercase;">{title}</h1>
    <p style="margin:12px 0 0;color:{_MUTED};font-size:16px;line-height:1.5;">{subtitle}</p>
  </td></tr>
  
  <!-- Content -->
  <tr><td style="padding:0 40px 32px;">{content}</td></tr>
  
  <!-- Footer -->
  <tr><td style="background-color:rgba(0,0,0,0.2);padding:24px;text-align:center;border-top:1px solid rgba(25,138,205,0.2);">
    <p style="font-size:12px;color:{_MUTED};margin:0;">
      © 2026 BrainHack. This is an automated message, please do not reply.
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

def get_registration_email_html(data: dict) -> str:
    full_name = data.get('full_name', 'Participant')
    email = data.get('email', '—')
    phone = data.get('phone', '—')
    reg_num = data.get('registration_number', '—')
    level = data.get('level', '—')
    speciality = data.get('speciality', '—')
    portfolio = data.get('portfolio_link') or '—'

    content = f"""
    <div style="background-color:rgba(0,1,1,0.4);border:1px solid rgba(25,138,205,0.2);border-radius:16px;padding:24px;margin-bottom:24px;">
      <h3 style="margin:0 0 16px;color:{_TEXT_COLOR};font-size:14px;letter-spacing:1px;text-transform:uppercase;border-bottom:1px solid rgba(25,138,205,0.2);padding-bottom:12px;">Submitted Information</h3>
      <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
        <tr><td style="padding:8px 0;color:{_MUTED};width:140px;">Full Name</td><td style="padding:8px 0;color:{_TEXT_COLOR};font-weight:600;">{full_name}</td></tr>
        <tr><td style="padding:8px 0;color:{_MUTED};">Email</td><td style="padding:8px 0;color:{_TEXT_COLOR};">{email}</td></tr>
        <tr><td style="padding:8px 0;color:{_MUTED};">Phone</td><td style="padding:8px 0;color:{_TEXT_COLOR};">{phone}</td></tr>
        <tr><td style="padding:8px 0;color:{_MUTED};">Student ID</td><td style="padding:8px 0;color:{_TEXT_COLOR};">{reg_num}</td></tr>
        <tr><td style="padding:8px 0;color:{_MUTED};">Level</td><td style="padding:8px 0;color:{_TEXT_COLOR};">{level}</td></tr>
        <tr><td style="padding:8px 0;color:{_MUTED};">Speciality</td><td style="padding:8px 0;color:{_TEXT_COLOR};">{speciality}</td></tr>
        <tr><td style="padding:8px 0;color:{_MUTED};">Portfolio</td><td style="padding:8px 0;color:{_TEXT_COLOR};"><a href="{portfolio}" style="color:{_ACCENT};text-decoration:none;">{portfolio}</a></td></tr>
      </table>
    </div>

    <!-- Selection Process -->
    <div style="background-color:rgba(0,1,1,0.4);border:1px solid rgba(25,138,205,0.2);border-radius:16px;padding:24px;">
      <h3 style="margin:0 0 20px;color:{_TEXT_COLOR};font-size:14px;letter-spacing:1px;text-transform:uppercase;display:flex;align-items:center;">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background-color:{_ACCENT};margin-right:10px;"></span> 
        Selection Process
      </h3>
      <div style="margin-bottom:20px;border-left:2px solid {_ACCENT_DARK};padding-left:16px;">
        <h4 style="margin:0 0 6px;color:{_ACCENT};font-size:15px;">1. Technical Review</h4>
        <p style="margin:0;color:{_MUTED};font-size:13px;line-height:1.5;">Your application is now under technical review.</p>
      </div>
      <div style="border-left:2px solid rgba(25,138,205,0.3);padding-left:16px;">
        <h4 style="margin:0 0 6px;color:{_MUTED};font-size:15px;">2. Final Confirmation</h4>
        <p style="margin:0;color:{_MUTED};font-size:13px;line-height:1.5;">You will receive a final confirmation email regardless of the outcome.</p>
      </div>
    </div>
    """
    return _wrap_html(content, "Registration Received", f"Hi {full_name}, your application for BrainHack 2026 has been successfully submitted.")

def get_accepted_email_html(name: str) -> str:
    content = f"""
    <div style="background-color:rgba(0,1,1,0.4);border:1px solid rgba(25,138,205,0.2);border-radius:16px;padding:24px;margin-bottom:24px;">
        <h2 style="color:{_ACCENT};font-size:20px;margin-top:0;">Congratulations, {name}! 🎉</h2>
        <p style="color:{_MUTED};line-height:1.7;">We're thrilled to confirm that your application to <strong>BrainHack</strong> has been <strong style="color:{_ACCENT};">accepted</strong>!</p>
        <div style="background:#0c0c26;border-left:3px solid {_ACCENT};padding:12px 16px;border-radius:0 8px 8px 0;margin:16px 0;color:{_TEXT_COLOR};">
            📅 <strong>April 17–18, 2026</strong><br>Day 1 kicks off at 09:00. Full schedule will be shared closer to the event.
        </div>
        <p style="color:{_MUTED};">Get ready to build, innovate, and compete. We'll send more details about the venue and logistics soon.</p>
    </div>
    """
    return _wrap_html(content, "Application Accepted", f"Welcome to BrainHack 2026, {name}!")

def get_rejected_email_html(name: str) -> str:
    content = f"""
    <div style="background-color:rgba(0,1,1,0.4);border:1px solid rgba(25,138,205,0.2);border-radius:16px;padding:24px;margin-bottom:24px;">
        <h2 style="color:{_RED_ACCENT};font-size:18px;margin-top:0;">Thank you for applying, {name}</h2>
        <p style="color:{_MUTED};line-height:1.7;">After careful review, we regret to inform you that we're unable to accommodate your participation in <strong>BrainHack</strong> this time due to limited spots.</p>
        <div style="background:#0c0c26;border-left:3px solid {_RED_ACCENT};padding:12px 16px;border-radius:0 8px 8px 0;margin:16px 0;color:{_TEXT_COLOR};">
            We truly appreciate your interest and encourage you to keep building and innovating.
        </div>
        <p style="color:{_MUTED};">Future editions of BrainHack will be open for registration! Thank you for being part of the InfoBrain community.</p>
    </div>
    """
    return _wrap_html(content, "Application Update", f"Update regarding your registration.")

