from django.urls import path

from parts_sheet import views

urlpatterns = [path("plugin/parts-sheet/", views.index),
               path("plugin/parts-sheet/assets/<str:filename>", views.asset),
               path("plugin/parts-sheet/api/<str:action>/", views.api)]
