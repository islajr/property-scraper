
$(window).scroll(function(){
    if ($(this).scrollTop() > 250) {
       $('.mobile-sticky-header').addClass('msh-sticky');
    } else {
       $('.mobile-sticky-header').removeClass('msh-sticky');
    }
});


$(window).scroll(function () {
    if ($(this).scrollTop() > 300) {
        $("#devStickynav").addClass("dsSticky");
    } else {
        $("#devStickynav").removeClass("dsSticky");
    }
});

$(window).scroll(function () {
    if ($(this).scrollTop() > 0) {
        $(".mc-header, .mc-body").addClass("mcSticky");
    } else {
        $(".mc-header, .mc-body").removeClass("mcSticky");
    }
});

var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
});

//
var selector = ".nav-main-dashboard li";

$(selector).on("click", function () {
    $(selector).removeClass("active");
    $(this).addClass("active");
});

//

$("a.extend-nav").click(function () {
    $(".adashboard-nav").toggleClass("extended");
});

//

$("#markAll").change(function () {
    // Check if the checkbox is checked
    if ($(this).is(":checked")) {
        // Show the div
        $("#markDiv").show();
        $('.filter-mark-all label.form-check-label').text('Unmark All');
    } else {
        // Hide the div if the checkbox is not checked
        $("#markDiv").hide();
        $('.filter-mark-all label.form-check-label').text('Mark All');

    }
});

// 

// Get references to the radio buttons and the content divs
const radio1 = $('#btnradio1');
const radio2 = $('#btnradio2');
const radio3 = $('#btnradio3');
const radio4 = $('#btnradio4');
const radio5 = $('#btnradio5');
const radio6 = $('#btnradio6');
const radio7 = $('#btnradio7');
const contentDiv1 = $('#contentDiv1');
const contentDiv2 = $('#contentDiv2');
const contentDiv3 = $('#contentDiv3');
const contentDiv4 = $('#contentDiv4');
const contentDiv5 = $('#contentDiv5');
const contentDiv6 = $('#contentDiv6');
const contentDiv7 = $('#contentDiv7');

// Add change event handlers to the radio buttons
radio1.change(function () {
  if (radio1.is(':checked')) {
    contentDiv1.show();
    contentDiv2.hide();
    contentDiv3.hide();
    contentDiv4.hide();
  }
});

radio2.change(function () {
  if (radio2.is(':checked')) {
    contentDiv1.hide();
    contentDiv2.show();
    contentDiv3.hide();
    contentDiv4.hide();
    contentDiv5.hide();
  }
});

radio3.change(function () {
  if (radio3.is(':checked')) {
    contentDiv1.hide();
    contentDiv2.hide();
    contentDiv3.show();
    contentDiv4.hide();
  }
});

radio4.change(function () {
    if (radio4.is(':checked')) {
      contentDiv1.hide();
      contentDiv2.hide();
      contentDiv3.hide();
      contentDiv4.show();
    }
  });

  radio5.change(function () {
    if (radio5.is(':checked')) {
      contentDiv1.show();
      contentDiv2.hide();
      contentDiv3.hide();
      contentDiv4.hide();
      contentDiv5.show();
      contentDiv6.hide();
      contentDiv7.hide();
    }
  });

  radio6.change(function () {
    if (radio6.is(':checked')) {
      contentDiv1.show();
      contentDiv2.hide();
      contentDiv3.hide();
      contentDiv4.hide();
      contentDiv5.hide();
      contentDiv6.show();
      contentDiv7.hide();
    }
  });

  radio7.change(function () {
    if (radio7.is(':checked')) {
      contentDiv1.show();
      contentDiv2.hide();
      contentDiv3.hide();
      contentDiv4.hide();
      contentDiv5.hide();
      contentDiv6.hide();
      contentDiv7.show();
    }
  });


  $("#nextTab").click(function () {
    var activeTab = $(".nav-link.active");
    let hasPrev = activeTab.parent().next().length;
    let hasNext = activeTab.parent().prev().length;
    let has1Next = hasNext === 1;
    let has1Prev = hasPrev === 1;
    let isSecondTab = has1Next && has1Prev;

    if(isSecondTab){
        document.getElementById('basic_form').submit()
    }else{

        if (activeTab.parent().next().length) {
            activeTab.parent().next().find(".nav-link").tab("show");
            $("#prevTab").show();
  
            // Check if this is the last tab and hide "Next step" button, then show "Submit" button
            if (!activeTab.parent().next().next().length) {
                $("#nextTab").hide();
                $("#submitButton").show();

            }
        }
    }
  });




  
  $("#prevTab").click(function () {
    var activeTab = $(".nav-link.active");
    if (activeTab.parent().prev().length) {
      activeTab.parent().prev().find(".nav-link").tab("show");
      if (!activeTab.parent().prev().prev().length) {
        $("#prevTab").hide();
      }
  
      // Always show "Submit" button when moving back
      $("#submitButton").hide();
  
      // Show "Next step" button since we are moving backward
      $("#nextTab").show();
    }
  });

  



// Get a reference to the radio button and label
const $dollarRadioButton = $("#addDollarPrice");
const $dollarDiv = $("#dollorPrice");
const $nairaDiv = $("#nairaPrice");

$dollarRadioButton.on('change', function () {
    if ($dollarRadioButton.is(':checked')) {
      $dollarDiv.show(); // Show the div when the checkbox is checked
      $nairaDiv.hide();
    } else {
      $dollarDiv.hide(); // Hide the div when the checkbox is unchecked
      $nairaDiv.show();
    }
});





  // Get a reference to the radio button and label
const $installmentP = $("#installmentPayment");
const $installmentDiv = $("#installmentP");

$installmentP.on('change', function () {
    if ($installmentP.is(':checked')) {
      $installmentDiv.show(); // Show the div when the checkbox is checked
    } else {
      $installmentDiv.hide(); // Hide the div when the checkbox is unchecked
    }
  });

// 

$(".share-sponsor").click(function(){
    $(".shareIcons").toggle();
  });


$(function () {
    var top = $(".agents-banner-search, .moving-banner-form").offset().top - parseFloat($(".agents-banner-search, .moving-banner-form").css("marginTop").replace(/auto/, 0));
    var footTop = $(".footer").offset().top - parseFloat($(".footer").css("marginTop").replace(/auto/, 0));

    var maxY = footTop - $(".agents-banner-search, .moving-banner-form").outerHeight();

    $(window).scroll(function (evt) {
        var y = $(this).scrollTop();
        if (y > top) {
            if (y < maxY) {
                $(".agents-banner-search, .moving-banner-form").addClass("fixed").removeAttr("style");
            } else {
                $(".agents-banner-search, .moving-banner-form")
                    .removeClass("fixed")
                    .css({
                        position: "absolute",
                        top: maxY - top + "px",
                    });
            }
        } else {
            $(".agents-banner-search, .moving-banner-form").removeClass("fixed");
        }
    });
});

$("#submitBtn").click(function () {
    const emailInput = $("#email");
    const successMessage = $("#successMessage");

    const email = emailInput.val().trim();
    const emailRegex = /^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/i;

    if (email === "" || !emailRegex.test(email)) {
        alert("Please enter a valid email address.");
    } else {
        $("#emailForm").hide();
        successMessage.show();
    }
});

// Add a change event handler to all checkboxes with class "myCheckbox" inside the container
$('.new-launch-tile input[type="checkbox"]').change(function () {
    // Check if any of the checkboxes inside the container are checked
    if ($('.new-launch-tile input[type="checkbox"]:checked').length > 0) {
        // If at least one checkbox is checked, add a class to the parent div
        $(this).closest(".new-launch-tile").addClass("checked");
    } else {
        // If none of the checkboxes are checked, remove the class from the parent div
        $(this).closest(".new-launch-tile").removeClass("checked");
    }
});

$(".virtualTours").slick({
    slidesToShow: 3,
    infinite: true,
    centerMode: true,
    prevArrow: '<button class="slide-arrow prev-arrow"><i class="fa-solid fa-angle-left"></i></button>',
    nextArrow: '<button class="slide-arrow prev-next"><i class="fa-solid fa-angle-right"></i></button>',
    centerPadding: "70px",
    responsive: [
        {
            breakpoint: 768, // Adjust as needed
            settings: {
                slidesToShow: 1,
                centerMode: false,
            },
        },
    ],
});
//

$(".testimonialSlider").slick({
    slidesToShow: 2,
    infinite: true,
    prevArrow: '<button class="slide-arrow prev-arrow"><i class="fa-solid fa-angle-left"></i></button>',
    nextArrow: '<button class="slide-arrow prev-next"><i class="fa-solid fa-angle-right"></i></button>',
    responsive: [
        {
            breakpoint: 768, // Adjust as needed
            settings: {
                slidesToShow: 1,
                centerMode: false,
            },
        },
    ],
});

$("input[type='radio']").change(function () {
    var selectedValue = $(this).val();

    if (selectedValue === "div1") {
        $("#div1").show();
        $("#div2").hide();
    } else if (selectedValue === "div2") {
        $("#div1").hide();
        $("#div2").show();
    }
});
//

$(".chart-tabs li a").click(function () {
    $(".chart-tabs li a").removeClass("active");
    $(this).addClass("active");
});

$(".table-two-accordion").click(function () {
    $(".table-two-accordion .table-two-row").removeClass("active");
    $(this).addClass("active");
});

//
$("#tab02").click(function () {
    $(".tab01").addClass("d-none");
    $(".tab02").addClass("d-grid");
    $(".tab02").removeClass("d-none");
    $(".tab02").removeClass("d-grid");
    $(".tab03").addClass("d-none");
});

$("#tab01").click(function () {
    $(".tab01").removeClass("d-none");
    $(".tab02").addClass("d-none");
    $(".tab01").removeClass("d-none");
});

$("#tab03").click(function () {
    $(".tab01").addClass("d-none");
    $(".tab02").addClass("d-none");
    $(".tab03").removeClass("d-none");
});

$("[data-trigger]").on("click", function () {
    var trigger_id = $(this).attr("data-trigger");
    $(trigger_id).toggleClass("show");
    $("body").toggleClass("offcanvas-active");
});

// close button
$(".btn-close").click(function (e) {
    $(".navbar-collapse").removeClass("show");
    $("body").removeClass("offcanvas-active");
});

$(window).scroll(function () {
    var scroll = $(window).scrollTop();

    if (scroll >= 500) {
        $(".main-nav").addClass("darkHeader");
    } else {
        $(".main-nav").removeClass("darkHeader");
    }
});

$(".show-more-btn").click(function () {
    if ($(".show-more-content").hasClass("show-more")) {
        $(this).text("Show Less");
    } else {
        $(this).text("Show More");
    }

    $(".show-more-content").toggleClass("show-more");
    $(".show-more-btn").toggleClass("show-more2");
});

$(".show-more-btn1").click(function () {
    if ($(".show-more-content1").hasClass("show-more1")) {
        $(this).text("Show Less");
    } else {
        $(this).text("Show More");
    }

    $(".show-more-content1").toggleClass("show-more1");
    $(".show-more-btn1").toggleClass("show-more3");
});

(function ($) {
    var Defaults = $.fn.select2.amd.require("select2/defaults");

    $.extend(Defaults.defaults, {
        dropdownPosition: "auto",
    });

    var AttachBody = $.fn.select2.amd.require("select2/dropdown/attachBody");

    var _positionDropdown = AttachBody.prototype._positionDropdown;

    AttachBody.prototype._positionDropdown = function () {
        var $window = $(window);

        var isCurrentlyAbove = this.$dropdown.hasClass("select2-dropdown--above");
        var isCurrentlyBelow = this.$dropdown.hasClass("select2-dropdown--below");

        var newDirection = null;

        var offset = this.$container.offset();

        offset.bottom = offset.top + this.$container.outerHeight(false);

        var container = {
            height: this.$container.outerHeight(false),
        };

        container.top = offset.top;
        container.bottom = offset.top + container.height;

        var dropdown = {
            height: this.$dropdown.outerHeight(false),
        };

        var viewport = {
            top: $window.scrollTop(),
            bottom: $window.scrollTop() + $window.height(),
        };

        var enoughRoomAbove = viewport.top < offset.top - dropdown.height;
        var enoughRoomBelow = viewport.bottom > offset.bottom + dropdown.height;

        var css = {
            left: offset.left,
            top: container.bottom,
        };

        // Determine what the parent element is to use for calciulating the offset
        var $offsetParent = this.$dropdownParent;

        // For statically positoned elements, we need to get the element
        // that is determining the offset
        if ($offsetParent.css("position") === "static") {
            $offsetParent = $offsetParent.offsetParent();
        }

        var parentOffset = $offsetParent.offset();

        css.top -= parentOffset.top;
        css.left -= parentOffset.left;

        var dropdownPositionOption = this.options.get("dropdownPosition");

        if (dropdownPositionOption === "above" || dropdownPositionOption === "below") {
            newDirection = dropdownPositionOption;
        } else {
            if (!isCurrentlyAbove && !isCurrentlyBelow) {
                newDirection = "below";
            }

            if (!enoughRoomBelow && enoughRoomAbove && !isCurrentlyAbove) {
                newDirection = "above";
            } else if (!enoughRoomAbove && enoughRoomBelow && isCurrentlyAbove) {
                newDirection = "below";
            }
        }

        if (newDirection == "above" || (isCurrentlyAbove && newDirection !== "below")) {
            css.top = container.top - parentOffset.top - dropdown.height;
        }

        if (newDirection != null) {
            this.$dropdown.removeClass("select2-dropdown--below select2-dropdown--above").addClass("select2-dropdown--" + newDirection);
            this.$container.removeClass("select2-container--below select2-container--above").addClass("select2-container--" + newDirection);
        }

        this.$dropdownContainer.css(css);
    };
})(window.jQuery);

//
$(".propertyType").select2({
    placeholder: "Type",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "below",
});

$(".noBedRooms").select2({
    placeholder: "Bedrooms",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "below",
});

$(".minPrice").select2({
    placeholder: "Min. Price",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "below",
});

$(".maxPrice").select2({
    placeholder: "Max. Price",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "below",
});

$(".minPrice1").select2({
    placeholder: "Min. Price",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "below",
    theme: "myCssClass",
});

$(".maxPrice1").select2({
    placeholder: "Max. Price",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "below",
    theme: "myCssClass",
});

$(".filterView").select2({
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "below",
});

$(".selectSort").select2({
    placeholder: "Sort",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "below",
});

$(".selectPrice").select2({
    placeholder: "Price",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "below",
});
$(".selectRooms").select2({
    placeholder: "Rooms",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "below",
});


// change dropdown position to auto and above

$(".minPriceAuto").select2({
    placeholder: "Min. Price",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "auto",
    containerCssClass: "above-other-elements",
});

$(".maxPriceAbove").select2({
    placeholder: "Max. Price",
    minimumResultsForSearch: Infinity,
    width: "100%",
    dropdownPosition: "auto",
    containerCssClass: "above-other-elements",
});









// document.getElementById('seeMoreBtn').addEventListener('click', function() {
//     // Show all hidden items
//     const hiddenItems = document.querySelectorAll('.hidden-item');
//     hiddenItems.forEach(item => {
//         item.style.display = 'list-item';
//     });
//     // Hide the See More button after clicking
//     this.style.display = 'none';
// });






$("button.navbar-toggler").click(function () {
    $("body").toggleClass("overflow-hidden");
});

//
$(".slick-partners").slick({
    slidesToShow: 4,
    infinite: true,
    slidesToScroll: 1,
    autoplay: false,
    autoplaySpeed: 2000,
    arrows: true,
    prevArrow: '<button class="slide-arrow prev-arrow"><i class="fa-solid fa-angle-left"></i></button>',
    nextArrow: '<button class="slide-arrow prev-next"><i class="fa-solid fa-angle-right"></i></button>',
    responsive: [
        {
            breakpoint: 991,
            settings: {
                slidesToShow: 3,
            },
        },
        {
            breakpoint: 767,
            settings: {
                slidesToShow: 2,
            },
        },
    ],
});

//

$(".slider-content").slick({
    slidesToShow: 1,
    slidesToScroll: 1,
    dots: true,
    fade: false,
    infinite: false,
    speed: 1000,
    asNavFor: ".slider-thumb",
    arrows: false,
});
$(".slider-thumb").slick({
    slidesToShow: 3,
    slidesToScroll: 1,
    asNavFor: ".slider-content",
    arrows: false,
    centerMode: false,
    focusOnSelect: true,
    // prevArrow: '<button class="slide-arrow prev-arrow"><i class="fa-solid fa-angle-left"></i></button>',
    // nextArrow: '<button class="slide-arrow prev-next"><i class="fa-solid fa-angle-right"></i></button>',
});

//



$(".property-sslider").on("init reInit afterChange", function(event, slick, currentSlide, nextSlide){
    var i = (currentSlide ? currentSlide : 0) + 1;
    var slideCount = slick.slideCount;
    $(".slide-counter .counter-text").text(i + "/" + slideCount); // Update the slide counter text
  });
  
  $(".property-sslider").slick({
    slidesToShow: 1,
    slidesToScroll: 1,
    arrows: true,
    fade: false,
    infinite: false,
    speed: 1000,
    prevArrow: '<button class="slide-arrow prev-arrow"><i class="fa-solid fa-angle-left"></i></button>',
    nextArrow: '<button class="slide-arrow prev-next"><i class="fa-solid fa-angle-right"></i></button>',
  });

// $(".property-sslider-thumb").slick({
//     slidesToShow: 5,
//     slidesToScroll: 1,
//     asNavFor: ".property-sslider",
//     dots: false,
//     centerMode: false,
//     focusOnSelect: true,
//     arrows: true,
//     prevArrow: '<button class="slide-arrow prev-arrow"><i class="fa-solid fa-angle-left"></i></button>',
//     nextArrow: '<button class="slide-arrow prev-next"><i class="fa-solid fa-angle-right"></i></button>',
//     responsive: [
//         {
//             breakpoint: 991,
//             settings: {
//                 slidesToShow: 4,
//             },
//         },
//         {
//             breakpoint: 767,
//             settings: {
//                 slidesToShow: 3,
//             },
//         },
//     ],
// });

$(".numbshow").click(function () {
    $(".numbshowed").removeClass("d-none");
    $(".numbshow").addClass("d-none");
});

$(function () {
    var top = $("#sidebar").offset().top - parseFloat($("#sidebar").css("marginTop").replace(/auto/, 0));
    var footTop = $("#footer").offset().top - parseFloat($("#footer").css("marginTop").replace(/auto/, 0));

    var maxY = footTop - $("#sidebar").outerHeight();

    $(window).scroll(function (evt) {
        var y = $(this).scrollTop();
        if (y > top) {
            if (y < maxY) {
                $("#sidebar").addClass("fixed").removeAttr("style");
            } else {
                $("#sidebar")
                    .removeClass("fixed")
                    .css({
                        position: "absolute",
                        top: maxY - top + "px",
                    });
            }
        } else {
            $("#sidebar").removeClass("fixed");
        }
    });
});

//
var ctx = document.getElementById("propertyChart01").getContext("2d");
var chart = new Chart(ctx, {
    // The type of chart we want to create
    type: "line", // also try bar or other graph types

    // The data for our dataset
    data: {
        labels: ["2011", "2014", "2018", "2022"],
        // Information about the dataset
        datasets: [
            {
                label: "Price/Sq. Ft.",
                backgroundColor: "#5743a308",
                borderColor: "#3c60b0",
                data: [26.4, 39.8, 66.8, 66.4],
            },
        ],
    },

    // Configuration options
    options: {
        layout: {
            padding: 10,
        },
        legend: {
            position: "bottom",
            labels: {
                boxWidth: 0,
            },
        },
    },
});

var ctx = document.getElementById("myChart").getContext("2d");

var myChart = new Chart(ctx, {
    type: "line",
    data: {
        labels: ["JAN", "FEB"],
        datasets: [
            {
                label: "Data",
                borderColor: "#80b6f4",
                pointBorderColor: "#80b6f4",
                pointBackgroundColor: "#80b6f4",
                pointHoverBackgroundColor: "#80b6f4",
                pointHoverBorderColor: "#80b6f4",
                pointBorderWidth: 3,
                pointHoverRadius: 3,
                pointHoverBorderWidth: 1,
                pointRadius: 3,
                fill: false,
                borderWidth: 2,
                data: [100, 120],
            },
        ],
    },
    options: {
        legend: {
            display: false,
        },
        scales: {
            yAxes: [
                {
                    ticks: {
                        fontColor: "rgba(0,0,0,0.5)",
                        fontStyle: "bold",
                        beginAtZero: true,
                        maxTicksLimit: 5,
                        padding: 5,
                    },
                    gridLines: {
                        drawTicks: false,
                        display: false,
                    },
                },
            ],
            xAxes: [
                {
                    gridLines: {
                        zeroLineColor: "transparent",
                    },
                    ticks: {
                        padding: 5,
                        fontColor: "rgba(0,0,0,0.5)",
                        fontStyle: "bold",
                    },
                },
            ],
        },
    },
});



function controlSelected(cntrl,value, mobility){

    console.log(typeof mobility);

    switch (cntrl){
        case "propertyType":
            document.getElementById('hidden-type').value = value
            document.getElementById('property-type').value = value
            break;
        case "minPrice":
            document.getElementById('min-price').value = value
            break;
        case "maxPrice":
            document.getElementById('max-price').value = value
            break;
        case "mode":
            document.getElementById('hidden-mode').value = value;
            document.getElementById('category-mode').value = value;
            break;
        case "beds":
            document.getElementById('num-beds').value = value;
            break;
    }
    if(mobility){
        document.getElementById("search_form").submit();
    }
}

// added for backward compatibility

