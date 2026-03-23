
  /**
   *
   * Copy & Paste
   * v1.9.6 [2011-11-11]
   *
   * Copyright (C) 1998-2011 DYNAMIC+. All rights reserved.
   *
   * http://e.xplo.it/$/$.copypaste.js
   * e@xplo.it
   *
   *
   * Permission is hereby granted, free of charge, to any person obtaining
   * a copy of this software and associated documentation files (the
   * "Software"), to deal in the Software without restriction, including
   * without limitation the rights to use, copy, modify, merge, publish,
   * distribute, sublicense, and/or sell copies of the Software, and to
   * permit persons to whom the Software is furnished to do so, subject to
   * the following conditions:
   *
   * The above copyright notice and this permission notice shall be
   * included in all copies or substantial portions of the Software.
   *
   * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
   * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
   * MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
   * NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
   * LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
   * OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
   * WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
   *
   */


  //window.$ && (function( $ )
	//var $ = $.noConflict();
(function($){
    $.fn.copypaste = function( oOptions, sourcePageType )
    {
      var oSettings =
      {
        clipboard:      '<b>%title%</b><br />\n&bdquo;%copy%&ldquo;<br />\n<br />\n<address><a href="%url%">%url%</a></address>',

        skip_tags:      ['INPUT', 'TEXTAREA'],
        base_node:      '<p></p>',

        word_separator: /[^A-Za-z0-9]+/i,
        trim:           true,

        min_chars:      0,
        max_chars:      0,

        min_words:      0,
        max_words:      0,

        safe_js_write:  true,
        track_events:   true
      };

      if ( oOptions )
      {
        if ( typeof oOptions == typeof function(){} )
          oOptions = { clipboard: oOptions };

        else if ( typeof oOptions != typeof {} )
          oOptions = { clipboard: ('' + oOptions) };

        $.extend( oSettings, oOptions );
      }


      this.bind
      (
        'copy',

        function( hEvent )
        {
          if ( oSettings.clipboard )
          {
            var mClipboard = oSettings.clipboard;
            var bSkip      = false;

            if ( oSettings.skip_tags )
            {
              var sTag = hEvent.target && hEvent.target.nodeName ? hEvent.target.nodeName.toUpperCase() : null;

              if ( sTag )
              {
                for ( var i in oSettings.skip_tags )
                {
                  //if ( oSettings.skip_tags[i].toUpperCase() == sTag )
//                  {
//                    bSkip = true;
//                    break;
//                  }
                }
              }
            }



            if ( !bSkip )
            {
              var fCopySkip   = function( sSelection )
              {
                if ( (oSettings.min_chars > 0 && sSelection.length < oSettings.min_chars) || (oSettings.max_chars > 0 && sSelection.length > oSettings.max_chars) )
                  return true;

                else if ( oSettings.min_words > 0 || oSettings.max_words > 0 )
                {
                  var aSelection = sSelection.split( oSettings.word_separator );

                  if ( (oSettings.min_words > 0 && aSelection.length < oSettings.min_words) || (oSettings.max_words > 0 && aSelection.length > oSettings.max_words) )
                    return true;
                }

                return false;
              };

              var fTrackEvent = function( sSelection )
              {
                if ( oSettings.track_events )
                {
                  //if ( window._gaq && _gaq.push )
				  if ( window.logGAEvent)
                  {

                    //_gaq.push( ['_trackEvent', 'Copy & Paste', location.href, sSelection] );
                      logGAEvent( sourcePageType, "Content Copy", sSelection + ' - ' + location.href);
                    return true;
                  }

                  else if ( window._gat && _gat._getTracker && window.pageTracker && pageTracker._trackEvent )
                  {
                    //pageTracker._trackEvent( 'Copy & Paste', location.href, sSelection );
					pageTracker._trackEvent( sourcePageType, "Content Copy", sSelection + ' - ' + location.href );
                    return true;
                  }

                  return false;
                }

                return null;
              };



              if ( typeof mClipboard != typeof function(){} )
              {
                var dDate       = new Date( );
                var fEncodeHTML = function( sString )
                {
                  return ('' + sString).split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;').split('"').join('&quot;').split('\'').join('&#39;');
                };


                mClipboard      = '' + mClipboard;
                mClipboard      = mClipboard.replace( /%title%/gi,      fEncodeHTML(document.title) );

                mClipboard      = mClipboard.replace( /%url%/gi,        fEncodeHTML(location.href) );
                mClipboard      = mClipboard.replace( /%domain%/gi,     fEncodeHTML(location.hostname) );
                mClipboard      = mClipboard.replace( /%path%/gi,       fEncodeHTML(location.pathname) );
                mClipboard      = mClipboard.replace( /%referrer%/gi,   fEncodeHTML(document.referrer) );

                mClipboard      = mClipboard.replace( /%date%/gi,       fEncodeHTML(dDate.toLocaleDateString()) );
                mClipboard      = mClipboard.replace( /%time%/gi,       fEncodeHTML(dDate.getHours() + ':' + ('00' + dDate.getMinutes()).slice(-2)) );
                mClipboard      = mClipboard.replace( /%timestamp%/gi,  fEncodeHTML(dDate.getTime()) );
                mClipboard      = mClipboard.replace( /%random%/gi,     fEncodeHTML(Math.round(Math.random() * 0x7fffffff)) );

                mClipboard      = mClipboard.replace( /%hide-start%/gi, '<span style="position:absolute; left:-999999px; top:auto; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); clip:rect(0,0,0,0);">' );
                mClipboard      = mClipboard.replace( /%hide-end%/gi,   '</span>' );

                mClipboard      = mClipboard.replace( /%browser%/gi,    fEncodeHTML(navigator.userAgent) );
                mClipboard      = mClipboard.replace( /%percent%/gi,    '%' );
              }

              try
              {
                if ( document.selection && document.selection.createRange && document.body && document.body.createTextRange && !window.opera )
                {
                  var hSelection = document.selection.createRange( );
                  var sSelection = oSettings.trim ? $.trim( hSelection.text ) : hSelection.text;

                  if ( sSelection && !fCopySkip(sSelection) )
                  {
                    var sRange     = hSelection.htmlText;
                    var sClipboard = typeof mClipboard == typeof function(){} ? mClipboard( sRange ) : mClipboard.replace( /%(copy|paste|clipboard)%/gi, sRange );

                    if ( sClipboard != null )
                    {
                      fTrackEvent( sSelection );

                      if ( oSettings.safe_js_write )
                      {
                        var hJsFunctions = [ document.write, document.writeln ];
                        document.write   = function(){ };
                        document.writeln = function(){ };
                      }

                      var hTmpNodeIn   = $(oSettings.base_node ? oSettings.base_node : '<span></span>').append( '' + sClipboard );
                      var hTmpNode     = $('<div></div>').css( {position:'absolute', left:$('body').scrollLeft() + 'px', top:$('body').scrollTop() + 'px', width:'1px', height:'1px', overflow:'hidden', clip:'rect(0 0 0 0)', color:'black', backgroundColor:'white', textAlign:'left', textDecoration:'none', border:'none'} ).append( '<br />' );

                      hTmpNode.append( hTmpNodeIn );
                      $('body').append( hTmpNode );


                      var hRange = document.body.createTextRange( );
                      hRange.moveToElementText( hTmpNodeIn.get(0) );
                      hRange.select( );

                      window.setTimeout( function()
                      {
                        hTmpNode.remove( );

                        if ( oSettings.safe_js_write )
                        {
                          document.write   = hJsFunctions[0];
                          document.writeln = hJsFunctions[1];
                        }


                        try
                        {
                          hSelection.select( );
                        }

                        catch ( hException )
                        {
                        }
                      }, 1 );
                    }
                  }
                }

                else if ( window.getSelection && document.createRange )
                {
                  var hSelection = getSelection( );
                  var sSelection = oSettings.trim ? $.trim( hSelection.toString() ) : hSelection.toString();

                  if ( sSelection && !fCopySkip(sSelection) )
                  {
                    if ( hSelection.getRangeAt )
                      var hRange = hSelection.getRangeAt( 0 );

                    else
                    {
                      var hRange = document.createRange( );

                      hRange.setStart( hSelection.anchorNode, hSelection.anchorOffset );
                      hRange.setEnd( hSelection.focusNode, hSelection.focusOffset );
                    }


                    var sRange     = $('<span></span>').append( hRange.cloneContents() ).html();
                    var sClipboard = typeof mClipboard == typeof function(){} ? mClipboard( sRange ) : mClipboard.replace( /%(copy|paste|clipboard)%/gi, sRange );

                    if ( sClipboard != null )
                    {
                      fTrackEvent( sSelection );

                      if ( oSettings.safe_js_write )
                      {
                        var hJsFunctions = [ document.write, document.writeln ];
                        document.write   = function(){ };
                        document.writeln = function(){ };
                      }

                      var hTmpNodeIn   = $(oSettings.base_node ? oSettings.base_node : '<span></span>').append( '' + sClipboard );
                      var hTmpNode     = $('<div></div>').css( {position:'absolute', left:'-999999px', top:'-999999px', maxWidth:'999998px', maxHeight:'999998px', overflow:'hidden', clip:'rect(0,0,0,0)', color:'black', backgroundColor:'white', textAlign:'left', textDecoration:'none', border:'none'} ).append( '<br />' );

                      hTmpNode.append( hTmpNodeIn );
                      $('body').append( hTmpNode );


                      if ( hSelection.selectAllChildren )
                        hSelection.selectAllChildren( hTmpNodeIn.get(0) );

                      else
                      {
                        var hTmpRange = document.createRange( );
                        hTmpRange.selectNodeContents( hTmpNodeIn.get(0) );

                        hSelection.removeAllRanges( );
                        hSelection.addRange( hTmpRange );
                      }

                      window.setTimeout( function()
                      {
                        hTmpNode.remove( );

                        if ( oSettings.safe_js_write )
                        {
                          document.write   = hJsFunctions[0];
                          document.writeln = hJsFunctions[1];
                        }


                        try
                        {
                          if ( hSelection.setBaseAndExtent )
                            hSelection.setBaseAndExtent( hRange.startContainer, hRange.startOffset, hRange.endContainer, hRange.endOffset );

                          else
                          {
                            hSelection.removeAllRanges( );
                            hSelection.addRange( hRange );
                          }
                        }

                        catch ( hException )
                        {
                        }
                      }, 1 );
                    }
                  }
                }
              }

              catch ( hException )
              {
              }
            }
          }
        }
      );

      return this;
    };



    $.copypaste = function( oOptions, sourcePageType )
    {
      return $(function(){ $('body').copypaste(oOptions, sourcePageType); });
    };

 })(jQuery);

 function enableContentCopyInfo(sourcePageType)
 {
	 try
	 {
		 (function($){
				$.copypaste('%copy% <br />\n<br />\nContent from '+app_name+'<br />\n<strong>Read more at</strong>: <a href=%url%?utm_source='+app_short_name+'&utm_medium=content+share&utm_campaign='+app_short_name+'+Content+Copy>%url%</a>', sourcePageType );

			})(jQuery);
	 }
	catch(error){}
 }
