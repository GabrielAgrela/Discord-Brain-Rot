"""
UI subpackage - Discord UI components (buttons, views, modals).
"""

from bot.ui.buttons.sounds import (
    ReplayButton, STSButton, IsolateButton, FavoriteButton, 
    ChangeSoundNameButton, DownloadSoundButton,
    PlaySoundButton, SlapButton, PlaySlapButton, AssignUserEventButton,
    STSCharacterSelectButton
)
from bot.ui.buttons.upload import (
    UploadSoundButton, UploadMP3FileButton, UploadChoiceView
)
from bot.ui.buttons.list_buttons import (
    ListSoundsButton, ListLastScrapedSoundsButton, SoundListButton,
    CreateListButton, AddToListButton, SoundListItemButton, 
    RemoveFromListButton, DeleteListButton
)
from bot.ui.buttons.navigation import (
    PaginationButton, SoundListPaginationButton, EventPaginationButton
)
from bot.ui.buttons.misc import (
    SubwaySurfersButton, SliceAllButton, FamilyGuyButton, 
    BrainRotButton, StatsButton, PlayRandomButton, 
    PlayRandomFavoriteButton, ListFavoritesButton, ListUserFavoritesButton
)
from bot.ui.buttons.admin import (
    MuteToggleButton
)
from bot.ui.buttons.events import (
    ConfirmUserEventButton, CancelButton, DeleteEventButton
)
from bot.ui.views.sounds import (
    SoundBeingPlayedView, SoundBeingPlayedWithSuggestionsView
)
from bot.ui.views.lists import (
    PaginatedSoundListView

)
from bot.ui.views.controls import (
    ControlsView, DownloadedSoundView, SoundView
)
from bot.ui.views.events import (
    UserEventSelectView, EventView, PaginatedEventView
)
from bot.ui.views.favorites import (
    PaginatedFavoritesView
)
from bot.ui.views.stats import (
    PaginatedStatsView
)
from bot.ui.views.onthisday import (
    OnThisDayView
)
from bot.ui.selects import (
    EventTypeSelect, UserSelect, SoundSelect, AddToListSelect,
    STSCharacterSelect, SimilarSoundsSelect, LoadingSimilarSoundsSelect
)
from bot.ui.modals import (
    UploadSoundModal, ChangeSoundNameModal, CreateListModalWithSoundAdd
)

__all__ = [
    # Buttons - Sounds
    'ReplayButton', 'STSButton', 'IsolateButton', 'FavoriteButton', 
    'ChangeSoundNameButton', 'DownloadSoundButton',
    'PlaySoundButton', 'SlapButton', 'PlaySlapButton', 'AssignUserEventButton',
    'STSCharacterSelectButton', 'UploadSoundButton', 'UploadMP3FileButton',
    
    # Buttons - Lists
    'ListSoundsButton', 'ListLastScrapedSoundsButton', 'SoundListButton',
    'CreateListButton', 'AddToListButton', 'SoundListItemButton', 
    'RemoveFromListButton', 'DeleteListButton',
    
    # Buttons - Navigation & Misc
    'PaginationButton', 'EventPaginationButton', 'SoundListPaginationButton',
    'SubwaySurfersButton', 'SliceAllButton', 'FamilyGuyButton', 
    'BrainRotButton', 'StatsButton', 'PlayRandomButton', 
    'PlayRandomFavoriteButton', 'ListFavoritesButton', 'ListUserFavoritesButton',
    
    # Buttons - Admin & Events
    'MuteToggleButton',
    'ConfirmUserEventButton', 'CancelButton', 'DeleteEventButton',
    
    # Views
    'SoundBeingPlayedView', 'SoundBeingPlayedWithSuggestionsView',
    'PaginatedSoundListView',

    'ControlsView', 'DownloadedSoundView', 'SoundView',
    'UserEventSelectView', 'EventView', 'PaginatedEventView',
    'PaginatedFavoritesView', 'PaginatedStatsView', 'OnThisDayView', 'UploadChoiceView',
    
    # Selects
    'EventTypeSelect', 'UserSelect', 'SoundSelect', 'AddToListSelect',
    'STSCharacterSelect', 'SimilarSoundsSelect', 'LoadingSimilarSoundsSelect',
    
    # Modals
    'UploadSoundModal', 'ChangeSoundNameModal', 'CreateListModalWithSoundAdd',
]
