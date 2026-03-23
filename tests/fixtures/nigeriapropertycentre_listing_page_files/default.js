
//slider
jQuery(document).ready(function ($) {
    var propertyImageSlider = $('#imageGallery').lightSlider({
        gallery: gGallery,
        item: 1,
        loop: true,
        mode: gMode,
        thumbItem: 5,
        speed: gSpeed,
        videojs: true,
        prevHtml: '<i class="fal fa-arrow-circle-left"></i>',
        nextHtml: '<i class="fal fa-arrow-circle-right"></i>',
        vertical: gVertical,
        keyPress: true,
        slideMargin: 0,
        galleryMargin: 0,
        thumbMargin: 0,
        enableDrag: false,
        vThumbWidth: 123,
        verticalHeight: 500,
        adaptiveHeight: false,
        currentPagerPosition: 'middle',
        onSliderLoad: function (el) {
            el.lightGallery({
                selector: '#imageGallery .lslide',
                speed: gSpeed,
                download: false,
                loadYoutubeThumbnail: false,
                thumbnail: isMobile == false
            });

            let propertyAvailability = $("#property-availability");
            propertyAvailability.detach().appendTo(".lSSlideWrapper");
            propertyAvailability.removeClass('hidden');
        },
        onBeforeSlide: function (el) {
        $('#lSSliderCounterCurrent').text(el.getCurrentSlideCount());
        }
    });

    /**
     * This gets executed when the back button is clicked.
     * Hide the price suggestion modal.
     */
    $(window).on('popstate', function () {

        $('.lg-close').click();
    });


    $( "#propertyLocation" ).change(function() {
        setLocBoxHeight();
    });

    $( "#search_jsForm" ).submit(function() {
        SetSearchPanelCookies();
    });

    if(propertyImageSlider.getTotalSlideCount)
    {
        $('#lSSliderCounterTotal').text(propertyImageSlider.getTotalSlideCount());
    }

    //google.maps.event.addDomListener(window, 'load', initialize);

    $('a[data-type="gmap"]').on('shown.bs.tab', function (e) {
        initialize();
    });

    if(user_logged_in === false) {
        $('a[data-type="showLoginMessage"]').on('click', function () {
            showLoginMessage();
        });
    }

    if(isMobile === true) {
        $('a[data-type="mobileContact"]').on('click', function () {
            logContactStat($(this).data('channel'));
        });
    }

    $('.js-p-image').on('click',function() {
        let urlReplace = "#imagePreviewer";
        history.pushState(null, null, urlReplace);
    });

    $('#report-button').on('click', function(e){
        $('#reportListing').modal('show').find('.modal-body').load($(this).data('href'));
      });

});


//map
var map;
var geocoder;
var myLatlng;

function initialize() {

    geocoder = new google.maps.Geocoder();

    //var address = '<?php echo trim($Product->address).', '.$locTemp.', '.$Product->name_state.', Nigeria'; ?>';

    geocoder.geocode( { 'address': address}, function(results, status) {
        if (status == google.maps.GeocoderStatus.OK) {
            myLatlng = results[0].geometry.location;
            map.setCenter(results[0].geometry.location);
            var marker = new google.maps.Marker({
                position: myLatlng,
                map: map,
                animation: google.maps.Animation.DROP,
                title: ''
            });
        } else {
            myLatlng = new google.maps.LatLng(0.000000, 0.000000);
            map.setCenter(myLatlng);
            var marker = new google.maps.Marker({
                position: myLatlng,
                map: map,
                animation: google.maps.Animation.DROP,
                title: ''
            });
        }
    });

    var mapOptions = {
        zoom: 15,
        scrollwheel: false,
        center: myLatlng,
        mapTypeId: google.maps.MapTypeId.ROADMAP
    }

    map = new google.maps.Map(document.getElementById('mapCanvas'), mapOptions);
}



//contact form
var exp = new Date(); // make new date object
exp.setTime(exp.getTime() + (1000 * 60 * 60 * 24 * 180)); // set it 180 days ahead

function SetFormCookies()
{
    setCookie("cFormName",document.getElementById('commentname').value,exp);
    setCookie("cFormEmail",document.getElementById('commentemail').value,exp);
    setCookie("cFormPhone",document.getElementById('commenttitle').value,exp);
}

function PopulateFormWithCookies()
{

    var cFormName = getCookie("cFormName");
    var cFormEmail = getCookie("cFormEmail");
    var cFormPhone = getCookie("cFormPhone");

    if(cFormName != null)
    {
        document.getElementById('commentname').value = cFormName;
    }

    if(cFormEmail != null)
    {
        document.getElementById('commentemail').value = cFormEmail;
    }

    if(cFormPhone != null)
    {
        document.getElementById('commenttitle').value = cFormPhone;
    }

}

function SetSTFFormCookies()
{
    setCookie("cFormName",document.getElementById('pas_name').value,expSTF);
    setCookie("cFormEmail",document.getElementById('pas_email').value,expSTF);
}

function PopulateSTFFormWithCookies()
{
    var cFormName = getCookie("cFormName");
    var cFormEmail = getCookie("cFormEmail");

    if(cFormName != null)
    {
        document.getElementById('pas_name').value = cFormName;
    }

    if(cFormEmail != null)
    {
        document.getElementById('pas_email').value = cFormEmail;
    }
}


$(document).ready(function() {
    if(contactFormAvailable) {PopulateFormWithCookies();}
    //PopulateSTFFormWithCookies();
});



$(document).ready(function() {

    var v = $("#commentForm").validate({
        rules: {
            // commenttitle: {
            //     required: function(element) {
            //         return $("#commentemail").val().length === 0 && $("#commenttitle").val().length === 0;
            //     }
            // },
            // commentemail: {
            //     required: function(element) {
            //         return $("#commentemail").val().length === 0 && $("#commenttitle").val().length === 0;
            //     }
            // }
        },
        messages:{
            // "commenttitle":{
            //     required:"Email or phone required"
            // },
            // "commentemail":{
            //     required:"Email or phone required"
            // }
        }
    });

    var agentContactOptions = {
        target:        	'#contact-form-container',
        beforeSubmit:	sendButtonClicked,
        success:       	agentContactSuccess
    };

    $('#commentForm').ajaxForm(agentContactOptions);
});

function agentContactSuccess()
{
    logGAEvent('Property Details', 'Contact Message Sent', contactEventLabel);
    messagePanelInView();
    logContactStat(2);
}

function messagePanelInView()
{
    $('html:not(:animated), body:not(:animated)').animate({
        scrollTop: $("#sMessage").offset().top
    }, 300);
}

$(document).ready(function() {
    var contactStatOptions = {};

    $('#contactStatForm').ajaxForm(contactStatOptions);
});

function logContactStat(channel)
{
    $("#channel").val(channel);
    $("#contactStatForm").submit();
}
function sendButtonClicked()
{
    document.getElementById('sendButtonSpan').innerHTML = 'Sending...';
    $('#sendButton').click(function(e){e.preventDefault();return false;});
    try
    {
        SetFormCookies();
    }
    catch(err)
    {
        //Handle errors here
    }
}


$( document ).ready(function() {
    if (isMobile != true) { enableContentCopyInfo("Property Details"); }
});

function showPhoneNumbers() {
    $("a[data-type='showPhoneNumber']").remove();
    let phoneHTML = '';
    let allPhoneNumbers = $("#fullPhoneNumbers").val().split(",");
    allPhoneNumbers.forEach(function(phone) {
        phoneHTML += `<a class="underline" href="tel:` + phone.trim() + `">` + phone.trim() + `</a>, `
    });

    $("span[data-type='phoneNumber']").html(phoneHTML.replace(/,\s*$/, ''));
    logContactStat(1);
}


function saveFavorite(product_id)
{
    processFavorite('/ajax/listings/favorites', 'post', product_id)
}

function deleteFavorite(product_id)
{
    processFavorite('/ajax/listings/favorites', 'delete', product_id)
}

function processFavorite(url, method, product_id)
{
    $("#fav-" + product_id + " > a").html('<i class="fal fa-circle-notch fa-spin fa-3x fa-fw"></i>');
    $("#processFavorite").attr('action', url);
    $("#_method").val(method);

    var favoriteOptions = {
        target:        '#fav-' + product_id,
        success:       favoriteSuccess,
        headers: {
            'X-CSRF-TOKEN': $('meta[name="csrf-token"]').attr('content')
        }
    };

    $('#processFavorite').ajaxForm(favoriteOptions);

    $("#processFavorite").submit();
}

function favoriteSuccess()
{

}
