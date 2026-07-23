from django.contrib import admin
from .models import Lead, Message, MediaFile, Tag, LeadTag


admin.site.register(Lead)
admin.site.register(Message)
admin.site.register(MediaFile)
admin.site.register(Tag)
admin.site.register(LeadTag)

